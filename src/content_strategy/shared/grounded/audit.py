"""Local append-only SQLite authority. Host-injected authorization/reviews are trusted seams."""

import csv
import hashlib
import html
import io
import json
import re
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, TypeAdapter

from .identity import canonical_json, identity_hash
from .models import ArtifactDigest, Digest, ExportReceipt, Identifier, ItemVersion, Record
from .validation import (
    Assessment,
    Checked,
    Content,
    CurrentEvidence,
    Policy,
    content_hash,
    validate,
)

MAX_BUNDLE_BYTES = 2 * 1024 * 1024
ACTOR = TypeAdapter(Identifier)


class GateError(ValueError):
    """Machine-safe refusal code; raw content is never interpolated."""


class ExportRequest(Record):
    idempotency_key: Identifier
    actor_label: Identifier
    generation: Digest
    policy_hash: Digest
    expected_sequence: int = Field(ge=0)
    items: tuple[ItemVersion, ...]


@dataclass(frozen=True)
class Bundle:
    receipt: ExportReceipt
    markdown: bytes
    csv: bytes
    historical_replay: bool


def _version(content: Content) -> ItemVersion:
    item = content.item
    return ItemVersion(
        item_id=item.item_id,
        revision=item.revision,
        content_hash=item.content_hash,
        evidence_generation=item.snapshot_id,
    )


def _csv_cell(value: str) -> str:
    offset = 0
    while offset < len(value) and (
        value[offset].isspace() or ord(value[offset]) < 32 or value[offset] in "\x7f\ufeff\u200b"
    ):
        offset += 1
    dangerous = value[offset:].startswith(("=", "+", "-", "@"))
    return "'" + value if dangerous or value.startswith(("\t", "\r", "\n", "\x00")) else value


def _markdown(value: str) -> str:
    escaped = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escaped)


class AuditStore:
    def __init__(
        self,
        database: str | Path,
        *,
        namespace: str,
        policy: Policy,
        resolver: CurrentEvidence,
        authorize: Callable[[str, str, Content], bool],
        assess: Callable[[Checked, Policy], Assessment],
        fault: Callable[[str], None] | None = None,
    ):
        if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace):
            raise GateError("invalid_namespace")
        self.namespace, self.policy, self.resolver = (
            namespace,
            Policy.model_validate(policy.model_dump()),
            resolver,
        )
        self.authorize, self.assess, self.fault = authorize, assess, fault
        self.connection = sqlite3.connect(database, isolation_level=None, timeout=5)
        self.connection.execute("PRAGMA foreign_keys=ON")
        migration = (
            Path(__file__).with_name("migrations").joinpath("001.sql").read_text(encoding="utf-8")
        )
        self.migration_sha256 = hashlib.sha256(migration.encode()).hexdigest()
        reference = sqlite3.connect(":memory:")
        reference.executescript(migration)
        self.expected_schema = self._schema(reference)
        reference.close()
        if self._schema(self.connection) and self._schema(self.connection) != self.expected_schema:
            self.connection.close()
            raise GateError("migration_schema_tamper")
        self.connection.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
        try:
            with self._transaction():
                record = self.connection.execute(
                    "SELECT sha256 FROM grounded_meta WHERE edition='001'"
                ).fetchone()
                if record is None:
                    self.connection.execute(
                        "INSERT INTO grounded_meta VALUES('001',?)", (self.migration_sha256,)
                    )
                elif record[0] != self.migration_sha256:
                    raise GateError("migration_hash_mismatch")
        except BaseException:
            self.connection.close()
            raise

    @staticmethod
    def _schema(connection):
        return tuple(
            connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name GLOB 'grounded_*' ORDER "
                "BY type,name"
            )
        )

    @contextmanager
    def _transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self._schema(self.connection) != self.expected_schema:
                raise GateError("migration_schema_tamper")
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def close(self):
        self.connection.close()

    @property
    def sequence(self) -> int:
        return self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM grounded_events WHERE namespace=?",
            (self.namespace,),
        ).fetchone()[0]

    def _cas(self, expected):
        if type(expected) is not int or self.sequence != expected:
            raise GateError("sequence_conflict")

    def _append(self, action, content=None, **payload):
        sequence, event_id = self.sequence + 1, "evt-" + uuid.uuid4().hex
        document = {"action": action, "at_utc": datetime.now(UTC).isoformat(), **payload}
        if content is not None:
            document["item"] = _version(content).model_dump(mode="python")
        self.connection.execute(
            "INSERT INTO grounded_events VALUES(?,?,?,?,?,?,?)",
            (
                self.namespace,
                sequence,
                event_id,
                action,
                content.item.item_id if content else None,
                content.item.revision if content else None,
                canonical_json(document),
            ),
        )
        return event_id

    def _context(self):
        row = self.connection.execute(
            "SELECT payload FROM grounded_events WHERE namespace=? AND action='context' "
            "ORDER BY sequence DESC LIMIT 1",
            (self.namespace,),
        ).fetchone()
        if row is None:
            raise GateError("context_not_initialized")
        return json.loads(row[0])

    def _current_context(self, generation):
        context = self._context()
        if context["generation"] != generation or context["policy_hash"] != self.policy.digest:
            raise GateError("stale_evidence_or_policy")

    def _latest_revision(self, item_id):
        return self.connection.execute(
            "SELECT COALESCE(MAX(revision),0) FROM grounded_versions WHERE namespace=? AND "
            "item_id=?",
            (self.namespace, item_id),
        ).fetchone()[0]

    def _load(self, item_id, revision):
        row = self.connection.execute(
            "SELECT content_json,content_hash,generation FROM grounded_versions WHERE "
            "namespace=? AND item_id=? AND revision=?",
            (self.namespace, item_id, revision),
        ).fetchone()
        if row is None:
            raise GateError("unknown_version")
        content = Content.model_validate_json(row[0])
        if (content.item.content_hash, content.item.snapshot_id) != row[
            1:
        ] or content.item.content_hash != content_hash(
            content.item, content.editorial, content.passages
        ):
            raise GateError("version_storage_mismatch")
        return content

    def _state(self, content):
        row = self.connection.execute(
            "SELECT action,event_id,payload FROM grounded_events WHERE namespace=? AND "
            "item_id=? AND revision=? ORDER BY sequence DESC LIMIT 1",
            (self.namespace, content.item.item_id, content.item.revision),
        ).fetchone()
        if row is None:
            raise GateError("missing_state_event")
        state = {
            "create": "draft",
            "invalidate": "draft",
            "approve": "approved",
            "reject": "rejected",
            "export": "exported",
        }[row[0]]
        return state, row[1], json.loads(row[2])

    def state(self, item_id: str, revision: int) -> str:
        with self._transaction():
            return self._state(self._load(item_id, revision))[0]

    def _latest(self, content):
        if self._latest_revision(content.item.item_id) != content.item.revision:
            raise GateError("stale_item_revision")

    def _checked(self, content):
        self._latest(content)
        self._current_context(content.item.snapshot_id)
        checked = validate(content, self.resolver, self.policy)
        if checked.report.structural_status != "valid":
            raise GateError("invalid_grounding")
        assessment = Assessment.model_validate(self.assess(checked, self.policy).model_dump())
        if (
            assessment.content_hash,
            assessment.evidence_hash,
            assessment.policy_hash,
            assessment.screen_edition,
        ) != (
            content.item.content_hash,
            checked.evidence_hash,
            self.policy.digest,
            self.policy.screen_edition,
        ):
            raise GateError("stale_assessment")
        if assessment.screen_status != "pass":
            raise GateError("screen_not_passed")
        if assessment.semantic_status != "supports":
            raise GateError("semantic_not_supported")
        return checked, assessment

    def _permission(self, actor, action, content):
        ACTOR.validate_python(actor)
        if self.authorize(actor, action, content) is not True:
            raise GateError("not_authorized")

    def _approval(self, content):
        checked, _ = self._checked(content)
        state, event_id, payload = self._state(content)
        if state != "approved" or payload["policy_hash"] != self.policy.digest:
            raise GateError("current_approval_required")
        if payload["item"] != _version(content).model_dump(mode="json"):
            raise GateError("approval_version_mismatch")
        approved = Assessment.model_validate(payload.get("assessment", {}))
        if (
            approved.content_hash,
            approved.evidence_hash,
            approved.policy_hash,
            approved.screen_edition,
            approved.screen_status,
            approved.semantic_status,
            payload.get("validator_version"),
        ) != (
            content.item.content_hash,
            checked.evidence_hash,
            self.policy.digest,
            self.policy.screen_edition,
            "pass",
            "supports",
            self.policy.validator_version,
        ):
            raise GateError("approval_assessment_mismatch")
        return checked, event_id

    def _parent(self, content):
        item = content.item
        if item.kind != "draft":
            return None
        parent = self._load(item.parent_id, item.parent_revision)
        self._approval(parent)
        if (
            parent.item.kind != "recommendation"
            or parent.item.scope != item.scope
            or parent.item.snapshot_id != item.snapshot_id
            or parent.passages != content.passages
            or {c.model_dump_json() for c in parent.item.citations}
            != {c.model_dump_json() for c in item.citations}
        ):
            raise GateError("parent_evidence_mismatch")
        return parent

    def activate_context(self, generation: str, *, expected_sequence: int):
        # Trusted host mutation. Automatically recorded invalidations are not human approvals.
        if not re.fullmatch(r"[0-9a-f]{64}", generation):
            raise GateError("invalid_generation")
        with self._transaction():
            self._cas(expected_sequence)
            existing = self.connection.execute(
                "SELECT payload FROM grounded_events WHERE namespace=? AND action='context' "
                "ORDER BY sequence DESC LIMIT 1",
                (self.namespace,),
            ).fetchone()
            if existing and (
                json.loads(existing[0])["generation"],
                json.loads(existing[0])["policy_hash"],
            ) == (generation, self.policy.digest):
                return
            self._append(
                "context",
                generation=generation,
                policy_hash=self.policy.digest,
                screen_edition=self.policy.screen_edition,
                validator_version=self.policy.validator_version,
            )
            for item_id, revision in self.connection.execute(
                "SELECT item_id,MAX(revision) FROM grounded_versions WHERE namespace=? "
                "GROUP BY item_id",
                (self.namespace,),
            ).fetchall():
                content = self._load(item_id, revision)
                if self._state(content)[0] in {"approved", "exported"}:
                    self._append(
                        "invalidate",
                        content,
                        reason="context_changed",
                        actor_label="system:context",
                    )

    def save(
        self, content: Content, *, actor_label: str, expected_revision: int, expected_sequence: int
    ):
        content = Content.model_validate(content.model_dump(mode="python"))
        with self._transaction():
            self._cas(expected_sequence)
            self._permission(actor_label, "save", content)
            self._current_context(content.item.snapshot_id)
            latest = self._latest_revision(content.item.item_id)
            if (
                type(expected_revision) is not int
                or latest != expected_revision
                or content.item.revision != latest + 1
            ):
                raise GateError("revision_conflict")
            if validate(content, self.resolver, self.policy).report.structural_status != "valid":
                raise GateError("invalid_grounding")
            self._parent(content)
            if latest:
                previous = self._load(content.item.item_id, latest)
                if self._state(previous)[0] in {"approved", "exported"}:
                    self._append(
                        "invalidate", previous, actor_label="system:edit", reason="content_changed"
                    )
                for child_id, child_revision in self.connection.execute(
                    "SELECT item_id,MAX(revision) FROM grounded_versions WHERE namespace=? "
                    "GROUP BY item_id",
                    (self.namespace,),
                ).fetchall():
                    child = self._load(child_id, child_revision)
                    if child.item.parent_id == content.item.item_id and self._state(child)[0] in {
                        "approved",
                        "exported",
                    }:
                        self._append(
                            "invalidate", child, actor_label="system:edit", reason="parent_changed"
                        )
            self.connection.execute(
                "INSERT INTO grounded_versions VALUES(?,?,?,?,?,?)",
                (
                    self.namespace,
                    content.item.item_id,
                    content.item.revision,
                    content.model_dump_json(),
                    content.item.content_hash,
                    content.item.snapshot_id,
                ),
            )
            self._append("create", content, actor_label=actor_label)

    def decide(
        self,
        item_id: str,
        revision: int,
        *,
        approve: bool,
        actor_label: str,
        expected_sequence: int,
    ):
        if type(approve) is not bool:
            raise GateError("explicit_decision_required")
        with self._transaction():
            self._cas(expected_sequence)
            content = self._load(item_id, revision)
            self._latest(content)
            self._permission(actor_label, "approve" if approve else "reject", content)
            if self._state(content)[0] != "draft":
                raise GateError("draft_state_required")
            if approve:
                _, assessment = self._checked(content)
                self._parent(content)
                return self._append(
                    "approve",
                    content,
                    actor_label=actor_label,
                    policy_hash=self.policy.digest,
                    validator_version=self.policy.validator_version,
                    screen_edition=self.policy.screen_edition,
                    assessment=assessment.model_dump(mode="python"),
                )
            return self._append("reject", content, actor_label=actor_label)

    def _stored_bundle(self, row, request):
        request_hash = identity_hash(request.model_dump(mode="python"))
        if row[0] != request_hash:
            raise GateError("idempotency_conflict")
        receipt = ExportReceipt.model_validate_json(row[1])
        payloads = {"md": bytes(row[2]), "csv": bytes(row[3])}
        for artifact in receipt.artifacts:
            payload = payloads[artifact.format]
            if (
                len(payload) != artifact.byte_length
                or hashlib.sha256(payload).hexdigest() != artifact.sha256
            ):
                raise GateError("receipt_bytes_tamper")
        if receipt.request_hash != request_hash:
            raise GateError("receipt_request_mismatch")
        if (
            receipt.item_versions != request.items
            or receipt.idempotency_key != request.idempotency_key
        ):
            raise GateError("receipt_version_mismatch")
        approved_versions = set()
        for event_id in receipt.approval_event_ids:
            event = self.connection.execute(
                "SELECT action,payload FROM grounded_events WHERE namespace=? AND event_id=?",
                (self.namespace, event_id),
            ).fetchone()
            if event is None or event[0] != "approve":
                raise GateError("receipt_approval_reference")
            payload = json.loads(event[1])
            version = ItemVersion.model_validate(payload["item"])
            approved_content = self._load(version.item_id, version.revision)
            if (
                version != _version(approved_content)
                or payload["policy_hash"] != request.policy_hash
            ):
                raise GateError("receipt_approval_binding")
            approved_versions.add(version)
        for version in request.items:
            if version not in approved_versions:
                raise GateError("receipt_missing_approval")
            content = self._load(version.item_id, version.revision)
            parent = self._load(content.item.parent_id, content.item.parent_revision)
            if _version(parent) not in approved_versions:
                raise GateError("receipt_missing_parent_approval")
        return Bundle(receipt, payloads["md"], payloads["csv"], True)

    def replay(self, request: ExportRequest) -> Bundle:
        # Read only by namespace and exact request, never by arbitrary disk path.
        request = ExportRequest.model_validate(request.model_dump(mode="python"))
        with self._transaction():
            row = self.connection.execute(
                "SELECT request_hash,receipt_json,markdown,csv FROM grounded_receipts WHERE "
                "namespace=? AND idempotency_key=?",
                (self.namespace, request.idempotency_key),
            ).fetchone()
            if row is None:
                raise GateError("unknown_receipt")
            for version in request.items:
                self._permission(
                    request.actor_label,
                    "read_receipt",
                    self._load(version.item_id, version.revision),
                )
            return self._stored_bundle(row, request)

    def read_receipt(self, idempotency_key: str, *, actor_label: str) -> Bundle:
        """Authorized historical download by a namespaced key, recoverable after restart."""
        ACTOR.validate_python(idempotency_key)
        with self._transaction():
            row = self.connection.execute(
                "SELECT request_hash,receipt_json,markdown,csv,request_json "
                "FROM grounded_receipts WHERE namespace=? AND idempotency_key=?",
                (self.namespace, idempotency_key),
            ).fetchone()
            if row is None:
                raise GateError("unknown_receipt")
            request = ExportRequest.model_validate_json(row[4])
            if request.idempotency_key != idempotency_key:
                raise GateError("receipt_request_mismatch")
            for version in request.items:
                self._permission(
                    actor_label, "read_receipt", self._load(version.item_id, version.revision)
                )
            return self._stored_bundle(row[:4], request)

    def export(self, request: ExportRequest) -> Bundle:
        request = ExportRequest.model_validate(request.model_dump(mode="python"))
        with self._transaction():
            request_hash = identity_hash(request.model_dump(mode="python"))
            previous = self.connection.execute(
                "SELECT request_hash,receipt_json,markdown,csv FROM grounded_receipts WHERE "
                "namespace=? AND idempotency_key=?",
                (self.namespace, request.idempotency_key),
            ).fetchone()
            if previous is not None:
                for version in request.items:
                    self._permission(
                        request.actor_label,
                        "read_receipt",
                        self._load(version.item_id, version.revision),
                    )
                return self._stored_bundle(previous, request)
            self._cas(request.expected_sequence)
            if request.policy_hash != self.policy.digest:
                raise GateError("stale_request_policy")
            self._current_context(request.generation)
            keys = [(v.item_id, v.revision) for v in request.items]
            if not keys or len(keys) > self.policy.max_bundle_items or len(set(keys)) != len(keys):
                raise GateError("invalid_bundle_items")
            contents, rendered, approval_ids = [], [], []
            for version in request.items:
                content = self._load(version.item_id, version.revision)
                self._permission(request.actor_label, "export", content)
                if (
                    _version(content) != version
                    or content.item.kind != "draft"
                    or content.item.snapshot_id != request.generation
                ):
                    raise GateError("export_version_mismatch")
                checked, approval_id = self._approval(content)
                parent = self._parent(content)
                _, parent_approval = self._approval(parent)
                approval_ids.extend((parent_approval, approval_id))
                contents.append(content)
                rendered.append(checked.rendered)
            md_parts, csv_parts = [], [b"item_id,revision,scope,text\r\n"]
            byte_count = len(csv_parts[0])
            for content, body in zip(contents, rendered, strict=True):
                md_part = (
                    ("\n\n" if md_parts else "")
                    + f"## {_markdown(content.item.item_id)}\n\n{_markdown(body)}"
                ).encode("utf-8")
                stream = io.StringIO(newline="")
                writer = csv.writer(stream, lineterminator="\r\n")
                writer.writerow(
                    tuple(
                        _csv_cell(value)
                        for value in (
                            content.item.item_id,
                            str(content.item.revision),
                            content.item.scope,
                            body,
                        )
                    )
                )
                csv_part = stream.getvalue().encode("utf-8")
                byte_count += len(md_part) + len(csv_part)
                if byte_count > MAX_BUNDLE_BYTES:
                    raise GateError("bundle_byte_limit")
                md_parts.append(md_part)
                csv_parts.append(csv_part)
            markdown, csv_bytes = b"".join(md_parts), b"".join(csv_parts)
            receipt = ExportReceipt(
                export_id="exp-" + uuid.uuid4().hex,
                idempotency_key=request.idempotency_key,
                request_hash=request_hash,
                item_versions=request.items,
                artifacts=tuple(
                    ArtifactDigest(
                        format=kind,
                        sha256=hashlib.sha256(payload).hexdigest(),
                        byte_length=len(payload),
                    )
                    for kind, payload in (("md", markdown), ("csv", csv_bytes))
                ),
                approval_event_ids=tuple(dict.fromkeys(approval_ids)),
                at_utc=datetime.now(UTC),
            )
            self.connection.execute(
                "INSERT INTO grounded_receipts VALUES(?,?,?,?,?,?,?)",
                (
                    self.namespace,
                    request.idempotency_key,
                    request_hash,
                    receipt.model_dump_json(),
                    markdown,
                    csv_bytes,
                    request.model_dump_json(),
                ),
            )
            for content in contents:
                self._append(
                    "export",
                    content,
                    actor_label=request.actor_label,
                    receipt_id=receipt.export_id,
                    policy_hash=self.policy.digest,
                )
            if self.fault:
                self.fault("before_commit")
        # Transaction context has committed before any bytes can escape this method.
        if self.fault:
            self.fault("after_commit")
        return Bundle(receipt, markdown, csv_bytes, False)
