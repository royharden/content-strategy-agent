"""Host-configured review operations over the actual source and approval stores."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from ..ingest import ingest_csv
from ..metrics import AnalysisConfig
from ..metrics.grounding import MetricsResolver
from ..shared.grounded.audit import AuditStore, Bundle, ExportRequest, GateError
from ..shared.grounded.models import Digest, Identifier, ItemVersion, Record, TagProvenance
from ..shared.grounded.validation import Assessment, Checked, Content, Policy
from ..storage import Retained, SourceStore


class Selection(Record):
    dataset_id: Annotated[str, Field(pattern=r"^s9-dataset-[0-9a-f]{32}$")]
    snapshot_id: Digest


class LocalReviewService:
    """Required trusted callbacks establish authority; request bodies cannot select an actor.

    authorize receives None for source/report/activation operations, and exact Content
    for item/receipt operations. assess is a host trust boundary, never an implicit
    passing model. Construction opens no database; each operation closes its connection.
    """

    def __init__(
        self,
        database: Path,
        *,
        namespace: str,
        actor_label: str,
        policy: Policy,
        authorize: Callable[[str, str, Content | None], bool],
        assess: Callable[[Checked, Policy], Assessment],
    ):
        import re

        if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace):
            raise GateError("invalid_namespace")
        if not callable(authorize) or not callable(assess):
            raise GateError("host_callbacks_required")
        self.database = Path(database)
        self.namespace = namespace
        self.actor_label = TypeAdapter(Identifier).validate_python(actor_label)
        self.policy = Policy.model_validate(policy.model_dump(mode="python"))
        self.authorize, self.assess = authorize, assess

    def _allow(self, action: str):
        if self.authorize(self.actor_label, action, None) is not True:
            raise GateError("not_authorized")

    def import_csv(
        self,
        payload: bytes,
        *,
        config: AnalysisConfig | None = None,
        tag_provenance: tuple[TagProvenance, ...] | None = None,
    ) -> Retained:
        self._allow("import_csv")
        ingest_csv(payload)  # Invalid CSV must not create/bootstrap a database.
        with SourceStore(self.database, namespace=self.namespace) as sources:
            return sources.import_csv(payload, config=config, tag_provenance=tag_provenance)

    def report(self, selection: Selection) -> Retained:
        self._allow("read_report")
        selection = Selection.model_validate(selection.model_dump(mode="python"))
        if not self.database.is_file():
            raise GateError("unknown_source")
        with SourceStore(self.database, namespace=self.namespace) as sources:
            return sources.load(selection.dataset_id, selection.snapshot_id)

    @contextmanager
    def _audit(self, selection: Selection) -> Iterator[AuditStore]:
        retained = self.report(selection)
        store = AuditStore(
            self.database,
            namespace=self.namespace,
            policy=self.policy,
            resolver=MetricsResolver(retained.report.snapshot),
            authorize=self.authorize,
            assess=self.assess,
        )
        try:
            yield store
        finally:
            store.close()

    def sequence(self, selection: Selection) -> int:
        with self._audit(selection) as store:
            return store.sequence

    def require_context(self, selection: Selection, *, expected_sequence: int | None = None) -> int:
        with self._audit(selection) as store:
            return store.require_context(
                selection.snapshot_id,
                actor_label=self.actor_label,
                expected_sequence=expected_sequence,
            )

    def history(self, selection: Selection):
        with self._audit(selection) as store:
            rows = store.history(actor_label=self.actor_label)
        return tuple(
            row for row in rows if row.version.evidence_generation == selection.snapshot_id
        )

    def preview(
        self, selection: Selection, version: ItemVersion, *, expected_sequence: int
    ) -> tuple[Checked, Assessment, int]:
        """Only this checked path may feed a browser body; raw read() is trusted storage."""
        self.require_context(selection, expected_sequence=expected_sequence)
        content = self.read(selection, version)
        with self._audit(selection) as store:
            checked, assessment = store.review(
                content.item.item_id, content.item.revision, actor_label=self.actor_label
            )
        sequence = self.require_context(selection, expected_sequence=expected_sequence)
        return checked, assessment, sequence

    def activate(self, selection: Selection, *, expected_sequence: int) -> int:
        self._allow("activate_context")
        with self._audit(selection) as store:
            store.activate_context(selection.snapshot_id, expected_sequence=expected_sequence)
            return store.sequence

    def save(
        self,
        selection: Selection,
        content: Content,
        *,
        expected_revision: int,
        expected_sequence: int,
    ) -> int:
        content = Content.model_validate(content.model_dump(mode="python"))
        if content.item.snapshot_id != selection.snapshot_id:
            raise GateError("selection_generation_mismatch")
        with self._audit(selection) as store:
            store.save(
                content,
                actor_label=self.actor_label,
                expected_revision=expected_revision,
                expected_sequence=expected_sequence,
            )
            return store.sequence

    def read(self, selection: Selection, version: ItemVersion) -> Content:
        """Trusted historical storage read; not a browser disclosure or approval capability."""
        version = ItemVersion.model_validate(version.model_dump(mode="python"))
        if version.evidence_generation != selection.snapshot_id:
            raise GateError("selection_generation_mismatch")
        with self._audit(selection) as store:
            content = store.read_content(
                version.item_id, version.revision, actor_label=self.actor_label
            )
        if (
            content.item.content_hash != version.content_hash
            or content.item.snapshot_id != version.evidence_generation
        ):
            raise GateError("version_mismatch")
        return content

    def decide(
        self,
        selection: Selection,
        version: ItemVersion,
        *,
        approve: bool,
        expected_sequence: int,
    ) -> str:
        # Immutable version verification plus the store's transactional CAS prevents
        # a read-to-decision race from approving an intervening revision/context.
        content = self.read(selection, version)
        with self._audit(selection) as store:
            return store.decide(
                content.item.item_id,
                content.item.revision,
                approve=approve,
                actor_label=self.actor_label,
                expected_sequence=expected_sequence,
            )

    def revoke(self, selection: Selection, version: ItemVersion, *, expected_sequence: int) -> int:
        content = self.read(selection, version)
        with self._audit(selection) as store:
            return store.revoke(
                content.item.item_id,
                content.item.revision,
                actor_label=self.actor_label,
                expected_sequence=expected_sequence,
            )

    def export(
        self,
        selection: Selection,
        *,
        idempotency_key: str,
        items: tuple[ItemVersion, ...],
        expected_sequence: int,
    ) -> Bundle:
        request = ExportRequest(
            idempotency_key=idempotency_key,
            actor_label=self.actor_label,
            generation=selection.snapshot_id,
            policy_hash=self.policy.digest,
            expected_sequence=expected_sequence,
            items=items,
        )
        with self._audit(selection) as store:
            return store.export(request)

    def download_receipt(self, selection: Selection, idempotency_key: str) -> Bundle:
        """Authorized historical receipt replay, even after context/edit invalidation."""
        with self._audit(selection) as store:
            return store.read_receipt(idempotency_key, actor_label=self.actor_label)
