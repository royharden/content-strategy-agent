"""Synthetic source-only bridge controls; never load DEV, Gold or held-out inputs."""

import hashlib
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from content_strategy.evaluation.replay_bridge import bind_authored_snapshot, public_identity
from content_strategy.ingest import ingest_csv
from content_strategy.metrics import AnalysisConfig, compute_metrics, source_default_tags
from content_strategy.shared.grounded.identity import canonical_json

CSV = (
    b"post_id,date,platform,text,impressions,likes,comments,shares,topic,format\r\n"
    b"b,2026-01-01T23:00:00-05:00,x,hello,100,10,2,1,workshop,\r\n"
    b"a,2026-01-02,linkedin,world,200,12,0,0,,story\r\n"
)


def frame(clock="posted-local"):
    source = {
        "media_type": "text/csv",
        "csv_text": CSV.decode(),
        "original_byte_sha256": hashlib.sha256(CSV).hexdigest(),
    }
    config = AnalysisConfig(clock).document()
    tags = [tag.model_dump(mode="python") for tag in source_default_tags(ingest_csv(CSV))]
    return source, config, tags


@pytest.mark.parametrize("clock", ["posted-local", "fixed-utc"])
def test_actual_default_producer_identity_and_config_string_exact(clock):
    source, config, tags = frame(clock)
    identity = public_identity(source, config, tags[::-1], original_csv=CSV)
    produced = compute_metrics(ingest_csv(CSV), AnalysisConfig(clock)).snapshot
    assert identity == produced.identity
    assert identity.config_json == canonical_json(config)
    assert identity.compute_version == "metrics.v1"


@pytest.mark.parametrize(
    "change",
    [
        "bytes",
        "sha",
        "field",
        "config",
        "clock",
        "tag",
        "missing",
        "duplicate",
        "model",
        "taxonomy",
    ],
)
def test_source_mismatch_cannot_be_reinterpreted_or_fitted(change):
    source, config, tags = deepcopy(frame())
    original = CSV
    if change == "bytes":
        original = CSV.replace(b"\r\n", b"\n")
    elif change == "sha":
        source["original_byte_sha256"] = "a" * 64
    elif change == "field":
        source["private_label"] = "never accepted"
    elif change == "config":
        config.pop("minimum_n")
    elif change == "clock":
        config["clock"] = "machine-local"
    elif change == "tag":
        tags[0]["value"] = "fitted"
    elif change == "missing":
        tags.pop()
    elif change == "duplicate":
        tags[0] = tags[1]
    elif change == "model":
        tags[0]["model"] = "inferred"
    elif change == "taxonomy":
        tags[0]["taxonomy_version"] = "other"
    with pytest.raises(ValueError):
        public_identity(source, config, tags, original_csv=original)


def test_original_opaque_metric_ids_and_order_kept_without_producer_authority():
    source, config, tags = frame()
    context = public_identity(source, config, tags, original_csv=CSV)
    produced = compute_metrics(ingest_csv(CSV)).snapshot
    # Authored legal IDs need not be the producer's slugs; no relabeling here.
    metrics = tuple(
        m.model_copy(update={"metric_id": f"opaque-{i}"}) for i, m in enumerate(produced.metrics)
    )
    before = [m.model_dump(mode="json") for m in metrics]
    bound = bind_authored_snapshot(
        metrics, (context.snapshot_id,), (context,), frozen_at=datetime(2026, 1, 5, tzinfo=UTC)
    )
    assert bound.evidence_origin == "authored_synthetic_replay" and not bound.producer_authority
    assert [m.model_dump(mode="json") for m in bound.snapshot.metrics] == before
    assert all(a is b for a, b in zip(bound.snapshot.metrics, metrics, strict=True))


@pytest.mark.parametrize("kind", ["none", "duplicate", "content", "metric", "empty"])
def test_ambiguous_or_mismatched_context_is_refused_without_remapping(kind):
    context = public_identity(*frame(), original_csv=CSV)
    metrics = compute_metrics(ingest_csv(CSV)).snapshot.metrics
    contexts = (context,)
    generations = (context.snapshot_id,)
    if kind == "none":
        contexts = ()
    elif kind == "duplicate":
        contexts = (context, context)
    elif kind == "content":
        generations = ("a" * 64,)
    elif kind == "metric":
        metrics = (metrics[0].model_copy(update={"snapshot_id": "a" * 64}),)
    elif kind == "empty":
        metrics = ()
    with pytest.raises(ValueError):
        bind_authored_snapshot(
            metrics, generations, contexts, frozen_at=datetime(2026, 1, 5, tzinfo=UTC)
        )
