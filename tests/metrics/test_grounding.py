from datetime import date

from content_strategy.ingest import Dataset, PostRow
from content_strategy.metrics import compute_metrics
from content_strategy.metrics.grounding import MetricsResolver
from content_strategy.shared.grounded import EvidenceKey, MetricCitation
from content_strategy.shared.grounded.validation import Policy, seal_content, validate


def test_real_analytics_adapter_accepts_exact_current_and_rejects_diagnostic_cross_scope_stale():
    rows = tuple(PostRow(str(i), date(2026, 10, 14), "x", "body", 10, 2, 0, 0) for i in range(5))
    snapshot = compute_metrics(Dataset(rows, "0" * 64)).snapshot
    resolver = MetricsResolver(snapshot)
    metric = next(m for m in snapshot.metrics if m.metric_id == "er.x.topic.untagged")
    citation = MetricCitation(
        snapshot_id=snapshot.snapshot_id,
        metric_id=metric.metric_id,
        scope="x",
        quoted_value="0.2",
        unit="ratio",
    )
    content = seal_content(
        item_id="choice",
        revision=1,
        kind="recommendation",
        scope="x",
        snapshot_id=snapshot.snapshot_id,
        text="Observed {{cite:er.x.topic.untagged}}",
        citations=(citation,),
    )
    policy = Policy(screen_edition="test-only")
    assert validate(content, resolver, policy).report.structural_status == "valid"
    assert (
        resolver.resolve(EvidenceKey(generation="f" * 64, evidence_id=metric.metric_id, scope="x"))
        is None
    )
    assert (
        resolver.resolve(
            EvidenceKey(
                generation=snapshot.snapshot_id, evidence_id=metric.metric_id, scope="linkedin"
            )
        )
        is None
    )
    assert resolver.current_generation("multi") is None
    diagnostic = next(m for m in snapshot.metrics if m.metric_id.startswith("diagnostic"))
    bad_citation = MetricCitation(
        snapshot_id=snapshot.snapshot_id,
        metric_id=diagnostic.metric_id,
        scope="x",
        quoted_value=diagnostic.value,
        unit="ratio",
    )
    diagnostic_item = seal_content(
        item_id="choice",
        revision=1,
        kind="recommendation",
        scope="x",
        snapshot_id=snapshot.snapshot_id,
        text="{{cite:" + diagnostic.metric_id + "}}",
        citations=(bad_citation,),
    )
    assert any(
        f.code == "uncitable_evidence"
        for f in validate(diagnostic_item, resolver, policy).report.failures
    )
