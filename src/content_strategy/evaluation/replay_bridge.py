"""Public-source identity bridge for authored replay evidence, never producer authority.

No fixture file discovery, Gold, scorer labels, source persistence or request execution.
Callers retain original input hashes and report refusals at their original positions.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from ..ingest import ingest_csv
from ..metrics import COMPUTE_VERSION, AnalysisConfig, source_default_tags
from ..shared.grounded.identity import canonical_json, identity_hash
from ..shared.grounded.models import Metric, MetricSnapshot, SnapshotIdentity, TagProvenance


def public_identity(
    source: Mapping,
    config: Mapping,
    tag_provenance: Sequence,
    *,
    original_csv: bytes,
) -> SnapshotIdentity:
    """Validate the complete public frame without computing an oracle metric table."""
    if not isinstance(source, Mapping) or set(source) != {
        "media_type",
        "csv_text",
        "original_byte_sha256",
    }:
        raise ValueError("public_source_shape")
    if source["media_type"] != "text/csv" or type(source["csv_text"]) is not str:
        raise ValueError("public_csv_required")
    encoded = source["csv_text"].encode("utf-8")
    if (
        type(original_csv) is not bytes
        or encoded != original_csv
        or hashlib.sha256(encoded).hexdigest() != source["original_byte_sha256"]
    ):
        raise ValueError("public_original_bytes_mismatch")
    dataset = ingest_csv(encoded)
    if not isinstance(config, Mapping):
        raise ValueError("full_public_config_required")
    effective = AnalysisConfig(clock=config.get("clock"))
    if canonical_json(config) != canonical_json(effective.document()):
        raise ValueError("full_public_config_mismatch")
    if not isinstance(tag_provenance, (tuple, list)):
        raise ValueError("full_public_provenance_required")
    tags = tuple(TagProvenance.model_validate(tag) for tag in tag_provenance)
    baseline = source_default_tags(dataset)
    # Identity's canonical ordering does not authorize dropping duplicate records.
    if len(tags) != len(baseline) or len({(t.source_id, t.field) for t in tags}) != len(tags):
        raise ValueError("full_public_provenance_mismatch")

    def order(tag):
        return tag.source_id, tag.field

    if tuple(sorted(tags, key=order)) != tuple(sorted(baseline, key=order)):
        raise ValueError("source_default_provenance_mismatch")
    return SnapshotIdentity(
        dataset_fingerprint=dataset.fingerprint,
        tag_provenance=tags,
        config_json=canonical_json(effective.document()),
        compute_version=COMPUTE_VERSION,
    )


@dataclass(frozen=True)
class AuthoredReplaySnapshot:
    snapshot: MetricSnapshot
    public_context_sha256: str
    evidence_origin: str = "authored_synthetic_replay"
    producer_authority: bool = False


def bind_authored_snapshot(
    metrics: tuple[Metric, ...],
    content_generations: tuple[str, ...],
    public_contexts: tuple[SnapshotIdentity, ...],
    *,
    frozen_at: datetime,
) -> AuthoredReplaySnapshot:
    """Preserve every original metric and require exactly one matching public context.

    frozen_at must be the caller's pinned public seal metadata. It has no identity
    authority. No SourceStore ID, producer slug or pointer is created here.
    """
    if type(metrics) is not tuple or not metrics or any(type(m) is not Metric for m in metrics):
        raise ValueError("original_metric_tuple_required")
    if type(content_generations) is not tuple or not content_generations:
        raise ValueError("original_content_generations_required")
    generations = {m.snapshot_id for m in metrics} | set(content_generations)
    if len(generations) != 1:
        raise ValueError("authored_generation_mismatch")
    if type(public_contexts) is not tuple or any(
        type(context) is not SnapshotIdentity for context in public_contexts
    ):
        raise ValueError("validated_public_contexts_required")
    matches = [context for context in public_contexts if context.snapshot_id in generations]
    if len(matches) != 1:
        raise ValueError("unique_public_context_required")
    context = matches[0]
    snapshot = MetricSnapshot(
        identity=context, snapshot_id=context.snapshot_id, created_at=frozen_at, metrics=metrics
    )
    return AuthoredReplaySnapshot(snapshot, identity_hash(context.identity_document()))
