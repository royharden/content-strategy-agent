"""Strict structural records. Constructing these objects never authorizes a side effect."""

from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from .identity import (
    DECIMAL_PATTERN,
    canonical_config,
    canonical_decimal,
    exact_decimal,
    identity_hash,
    normalized_string,
)

ExactDecimal = Annotated[
    Decimal,
    BeforeValidator(exact_decimal),
    PlainSerializer(canonical_decimal, return_type=str),
    WithJsonSchema({"type": "string", "pattern": "^" + DECIMAL_PATTERN + "$"}),
]
Text = Annotated[str, BeforeValidator(normalized_string), Field(min_length=1, max_length=16384)]
Identifier = Annotated[
    str,
    BeforeValidator(normalized_string),
    Field(min_length=1, max_length=256, pattern=r"^\S(?:[^\x00-\x1f]*\S)?$"),
]
Digest = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(gt=0)]
NonnegativeInt = Annotated[int, Field(ge=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, validate_default=True)
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be integer 1, not coercible data")
        return value


class EvidenceKey(Record):
    """Domain-neutral resolution key; a reference is not proof that evidence exists."""

    generation: Digest
    evidence_id: Identifier
    scope: Identifier


class TagProvenance(Record):
    source_id: Identifier
    field: Identifier
    value: Text
    method: Identifier
    model: Identifier | None = None
    taxonomy_version: Identifier
    threshold: ExactDecimal | None = None

    @field_validator("threshold")
    @classmethod
    def probability_range(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not Decimal(0) <= value <= Decimal(1):
            raise ValueError("A tagging threshold must be within [0,1]")
        return value


class SnapshotIdentity(Record):
    identity_version: Literal["snapshot-identity.v1"] = "snapshot-identity.v1"
    dataset_fingerprint: Digest
    tag_provenance: tuple[TagProvenance, ...]
    config_json: Annotated[str, BeforeValidator(canonical_config)]
    compute_version: Identifier

    @field_validator("tag_provenance")
    @classmethod
    def unique_sorted_tags(cls, value: tuple[TagProvenance, ...]) -> tuple[TagProvenance, ...]:
        keys = [(tag.source_id, tag.field) for tag in value]
        if len(set(keys)) != len(keys):
            raise ValueError("Conflicting or duplicate source/field provenance")
        return tuple(sorted(value, key=lambda tag: (tag.source_id, tag.field)))

    def identity_document(self) -> dict[str, object]:
        """Exact immutable wire document; config text is already canonicalized."""
        return self.model_dump(mode="python")

    @property
    def snapshot_id(self) -> str:
        return identity_hash(self.identity_document())


class Metric(Record):
    metric_id: Identifier
    snapshot_id: Digest
    scope: Identifier
    definition: Text
    value: ExactDecimal | None
    unit: Identifier
    sample_size: NonnegativeInt
    excluded_size: NonnegativeInt = 0
    computed_by: Identifier
    status: Literal["ok", "insufficient_data", "unavailable"]
    status_reason: Text | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if self.status == "ok":
            if self.value is None or self.sample_size == 0 or self.status_reason is not None:
                raise ValueError(
                    "An ok metric requires a value, positive sample and no failure reason"
                )
        elif self.status_reason is None:
            raise ValueError("Unavailable/insufficient metrics require an explicit reason")
        if self.status == "unavailable" and self.value is not None:
            raise ValueError("Unavailable metrics cannot fabricate a value")
        return self


class MetricSnapshot(Record):
    identity: SnapshotIdentity
    snapshot_id: Digest
    created_at: AwareDatetime
    metrics: tuple[Metric, ...]

    @model_validator(mode="after")
    def consistent_generation(self) -> Self:
        if self.snapshot_id != self.identity.snapshot_id:
            raise ValueError(
                "Snapshot ID differs from its exact source/config/tag/computation identity"
            )
        keys = [metric.metric_id for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate metric ID within snapshot")
        if any(metric.snapshot_id != self.snapshot_id for metric in self.metrics):
            raise ValueError("Metric belongs to another snapshot")
        return self


class MetricCitation(Record):
    snapshot_id: Digest
    metric_id: Identifier
    scope: Identifier
    quoted_value: ExactDecimal
    unit: Identifier

    @property
    def key(self) -> EvidenceKey:
        return EvidenceKey(
            generation=self.snapshot_id, evidence_id=self.metric_id, scope=self.scope
        )


class ItemVersion(Record):
    item_id: Identifier
    revision: PositiveInt
    content_hash: Digest
    evidence_generation: Digest


class GroundedItem(Record):
    """A proposed item. Shape/hash strings do not establish grounding, approval or provenance."""

    item_id: Identifier
    revision: PositiveInt
    kind: Identifier
    scope: Identifier
    snapshot_id: Digest
    text: Text
    citations: tuple[MetricCitation, ...]
    content_hash: Digest
    parent_id: Identifier | None = None
    parent_revision: PositiveInt | None = None

    @model_validator(mode="after")
    def paired_parent(self) -> Self:
        if (self.parent_id is None) != (self.parent_revision is None):
            raise ValueError("Parent ID and revision must appear together")
        return self


class ValidationFailure(Record):
    code: Identifier
    reference_id: Identifier | None = None
    detail: Text | None = None


class ValidationReport(Record):
    item_id: Identifier
    revision: PositiveInt
    snapshot_id: Digest
    structural_status: Literal["valid", "invalid"]
    failures: tuple[ValidationFailure, ...]
    semantic_status: Literal["not_run", "supports", "contradicts", "says_nothing", "unknown"]
    validator_version: Identifier

    @model_validator(mode="after")
    def consistent_report(self) -> Self:
        if (self.structural_status == "invalid") != bool(self.failures):
            raise ValueError(
                "An invalid report needs failures; a valid report cannot carry failures"
            )
        return self


class ApprovalEvent(Record):
    """Untrusted event data, not an authenticated human decision or transition engine."""

    event_id: Identifier
    sequence: PositiveInt
    item: ItemVersion
    from_state: Literal["draft", "approved", "rejected", "exported"]
    to_state: Literal["draft", "approved", "rejected", "exported"]
    actor_label: Identifier
    at_utc: AwareDatetime
    policy_sha256: Digest
    reason: Text | None = None
    idempotency_key: Identifier | None = None

    @field_validator("at_utc")
    @classmethod
    def utc_timestamp(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("Audit metadata must explicitly use UTC")
        return value


class ArtifactDigest(Record):
    format: Literal["md", "csv"]
    sha256: Digest
    byte_length: PositiveInt


class ExportReceipt(Record):
    """Receipt shape only: no bytes rendered, no approval resolved and no files written."""

    export_id: Identifier
    idempotency_key: Identifier
    request_hash: Digest
    item_versions: tuple[ItemVersion, ...]
    artifacts: tuple[ArtifactDigest, ...]
    approval_event_ids: tuple[Identifier, ...]
    at_utc: AwareDatetime

    @model_validator(mode="after")
    def bounded_bundle_shape(self) -> Self:
        if len(self.artifacts) != 2 or {a.format for a in self.artifacts} != {"md", "csv"}:
            raise ValueError("One two-format Markdown/CSV bundle is required")
        if sum(a.byte_length for a in self.artifacts) > 2 * 1024 * 1024:
            raise ValueError("Artifact bundle exceeds 2 MiB")
        if not self.item_versions or not self.approval_event_ids:
            raise ValueError("Receipt references are required, but do not prove authorization")
        keys = [(v.item_id, v.revision) for v in self.item_versions]
        if len(keys) != len(set(keys)) or len(set(self.approval_event_ids)) != len(
            self.approval_event_ids
        ):
            raise ValueError("Duplicate item versions or approval references")
        if self.at_utc.utcoffset() != timedelta(0):
            raise ValueError("Receipt metadata must explicitly use UTC")
        return self


PUBLIC_MODELS = (
    EvidenceKey,
    TagProvenance,
    SnapshotIdentity,
    Metric,
    MetricSnapshot,
    MetricCitation,
    ItemVersion,
    GroundedItem,
    ValidationFailure,
    ValidationReport,
    ApprovalEvent,
    ArtifactDigest,
    ExportReceipt,
)
