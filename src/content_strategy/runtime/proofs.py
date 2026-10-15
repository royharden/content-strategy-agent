"""App-owned append-only receipts for successful authored mock execution.

The trusted local host writes these receipts from its actual completed operation.
There is no assessment/proof submission endpoint and a receipt grants no approval.
"""

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..metrics.grounding import MetricsResolver
from ..shared.grounded.audit import GateError
from ..shared.grounded.identity import canonical_json, identity_hash
from ..shared.grounded.validation import Assessment, Checked, Policy, validate
from .mock import MockPlan

TABLE = (
    "CREATE TABLE mock_execution_proofs (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "namespace TEXT NOT NULL, content_hash TEXT NOT NULL, evidence_hash TEXT NOT NULL, "
    "policy_hash TEXT NOT NULL, screen_edition TEXT NOT NULL, payload TEXT NOT NULL, "
    "sha256 TEXT NOT NULL)"
)
UPDATE = (
    "CREATE TRIGGER mock_execution_proofs_no_update BEFORE UPDATE ON mock_execution_proofs "
    "BEGIN SELECT RAISE(ABORT, 'immutable_mock_proof'); END"
)
DELETE = (
    "CREATE TRIGGER mock_execution_proofs_no_delete BEFORE DELETE ON mock_execution_proofs "
    "BEGIN SELECT RAISE(ABORT, 'immutable_mock_proof'); END"
)
DDL = {
    "mock_execution_proofs": TABLE,
    "mock_execution_proofs_no_update": UPDATE,
    "mock_execution_proofs_no_delete": DELETE,
}


class ProofStore:
    def __init__(self, database: Path, *, namespace: str):
        if type(namespace) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace):
            raise GateError("invalid_namespace")
        self.database, self.namespace = Path(database), namespace

    @contextmanager
    def _open(self, *, create=False):
        if self.database.is_symlink() or not self.database.is_file():
            raise GateError("proof_store_unavailable")
        connection = sqlite3.connect(self.database, isolation_level=None, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE" if create else "BEGIN")
            found = {
                row["name"]: row["sql"]
                for row in connection.execute(
                    "SELECT name,sql FROM sqlite_master WHERE name IN (?,?,?)", tuple(DDL)
                )
            }
            if not found and create:
                for sql in DDL.values():
                    connection.execute(sql)
                found = dict(DDL)
            if found != DDL:
                raise GateError("proof_schema_unavailable")
            yield connection
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise GateError("proof_storage_error") from None
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def retain(self, runtime: MockPlan) -> int:
        """Trusted host only; accept the actual run's result, never a caller-made Strategy."""
        if (
            type(runtime) is not MockPlan
            or not runtime.used
            or runtime.closed
            or runtime.strategy is None
        ):
            raise GateError("actual_completed_mock_required")
        kind = runtime.kind
        if kind not in {"plan", "draft"}:
            raise GateError("mock_operation_kind")
        support_stage = "support" if kind == "plan" else "support.draft"
        generation_purpose = "s9." + kind + ".initial"
        support_purpose = "s9." + support_stage + ".initial"
        known = {
            "screen." + kind + ".initial",
            kind + ".initial",
            "screen." + support_stage + ".initial",
            support_stage + ".initial",
        }
        if (
            runtime.ports.completed != known
            or runtime.ledger.operation_state(runtime.allocation) != "complete"
        ):
            raise GateError("mock_operation_incomplete")
        calls = runtime.ports.calls
        if len(runtime.ports.results) != 2:
            raise GateError("mock_result_coverage")
        generation, support = runtime.ports.results
        for purpose, result in zip(
            (generation_purpose, support_purpose), (generation, support), strict=True
        ):
            call = calls[purpose]
            result.validate_for(call.request)
            if (
                result.status != "ok"
                or result.origin != "mock"
                or result.source_capture is None
                or result.source_capture.origin != "synthetic"
                or result.current_external_cost_usd != "0"
                or result.accounting_ref != runtime.allocation.allocation_id
                or call.binding.context.consumer_namespace != self.namespace
                or call.binding.ledger is not runtime.ledger
                or call.binding.allocation is not runtime.allocation
            ):
                raise GateError("mock_result_binding")
        if runtime.ledger.totals()["dispatched_attempts"] != 0:
            raise GateError("mock_dispatch_forbidden")
        policy = runtime.pipeline.grounded_policy
        screen = runtime.ports.screen_results.get("s9.screen." + support_stage + ".initial")
        if (
            screen is None
            or screen.decision != "pass"
            or screen.coverage != "complete"
            or screen.method != "typed_mock"
            or screen.policy_sha256 != policy.screen_edition
            or screen.accounting_ref != runtime.allocation.allocation_id
            or screen.input_sha256 != calls[support_purpose].assembly.digest
        ):
            raise GateError("mock_screen_binding")
        stages = {}
        for purpose, (call, native) in runtime.ports.screens.items():
            stages[purpose] = {
                "input_sha256": call.assembly.digest,
                "original_request_sha256": native.request.request_sha256,
                "wrapped_state_sha256": native.request.wrapped.sha256,
            }
        provenance = {
            "origin": "authored_synthetic_mock",
            "quality_measurement": False,
            "allocation": runtime.allocation.model_dump(mode="python"),
            "generation_capture": generation.source_capture.model_dump(mode="python"),
            "support_capture": support.source_capture.model_dump(mode="python"),
            "screens": stages,
        }
        # SourceCaptureRef contains measured latency floats only for live captures;
        # these original synthetic refs retain null latency/unknown usage.
        rows = []
        for accepted in runtime.accepted:
            checked = validate(accepted.checked.content, MetricsResolver(runtime.snapshot), policy)
            item = checked.content.item
            answer = support.typed.answers.get(item.item_id)
            if (
                checked.report.failures
                or checked != accepted.checked
                or answer is None
                or answer.type != "choice"
                or answer.choice != "supports"
                or accepted.screen != screen
            ):
                raise GateError("mock_item_binding")
            assessment = Assessment(
                content_hash=item.content_hash,
                evidence_hash=checked.evidence_hash,
                policy_hash=policy.digest,
                screen_edition=policy.screen_edition,
                screen_status="pass",
                semantic_status=answer.choice,
            )
            payload = {
                "edition": "s9-mock-proof.v1",
                "namespace": self.namespace,
                "assessment": assessment.model_dump(mode="python"),
                "provenance": provenance,
            }
            rows.append(
                (
                    self.namespace,
                    assessment.content_hash,
                    assessment.evidence_hash,
                    assessment.policy_hash,
                    assessment.screen_edition,
                    canonical_json(payload),
                    identity_hash(payload),
                )
            )
        with self._open(create=True) as connection:
            connection.executemany(
                "INSERT INTO mock_execution_proofs "
                "(namespace,content_hash,evidence_hash,policy_hash,screen_edition,payload,sha256) "
                "VALUES (?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def assess(self, checked: Checked, policy: Policy) -> Assessment:
        key = (
            self.namespace,
            checked.content.item.content_hash,
            checked.evidence_hash,
            policy.digest,
            policy.screen_edition,
        )
        with self._open() as connection:
            row = connection.execute(
                "SELECT payload,sha256 FROM mock_execution_proofs "
                "WHERE namespace=? AND content_hash=? "
                "AND evidence_hash=? AND policy_hash=? AND screen_edition=? "
                "ORDER BY sequence DESC LIMIT 1",
                key,
            ).fetchone()
        if row is None:
            raise GateError("assessment_unavailable")
        try:
            payload = json.loads(row["payload"])
            if (
                canonical_json(payload) != row["payload"]
                or identity_hash(payload) != row["sha256"]
                or payload["edition"] != "s9-mock-proof.v1"
                or payload["namespace"] != self.namespace
                or payload["provenance"]["origin"] != "authored_synthetic_mock"
                or payload["provenance"]["quality_measurement"] is not False
            ):
                raise ValueError
            result = Assessment.model_validate(payload["assessment"])
            if (
                self.namespace,
                result.content_hash,
                result.evidence_hash,
                result.policy_hash,
                result.screen_edition,
            ) != key:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise GateError("invalid_mock_proof") from None
        return result
