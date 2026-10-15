"""Tiny local development controls: real S9 validation feeds published S2 math."""

from decimal import Decimal

import pytest

from content_strategy.shared.evalkit.models import MetricSpec, Outcome
from content_strategy.shared.evalkit.reporting import metric_row
from content_strategy.shared.evalkit.statistics import accuracy, confusion_counts, wilson_interval
from content_strategy.shared.grounded.models import Metric, MetricCitation
from content_strategy.shared.grounded.validation import Policy, seal_content, validate

GEN = "a" * 64


class Resolver:
    def current_generation(self, scope):
        return GEN if scope == "linkedin" else None

    def resolve(self, key):
        if key.generation != GEN or key.evidence_id != "rate" or key.scope != "linkedin":
            return None
        return Metric(
            metric_id="rate",
            snapshot_id=GEN,
            scope="linkedin",
            definition="Local control",
            value=Decimal("0.1"),
            unit="ratio",
            sample_size=5,
            computed_by="test.v1",
            status="ok",
        )


def outcome(item, expected, *, unit="ratio", status="ok"):
    content = seal_content(
        item_id=item,
        revision=1,
        kind="recommendation",
        scope="linkedin",
        snapshot_id=GEN,
        text="Observed {{cite:rate}}",
        citations=(
            MetricCitation(
                snapshot_id=GEN,
                metric_id="rate",
                scope="linkedin",
                quoted_value="0.1",
                unit=unit,
            ),
        ),
    )
    checked = validate(content, Resolver(), Policy(screen_edition="test.v1"))
    observed = checked.report.structural_status == "valid"
    return Outcome(
        item_id=item,
        group_id="local-" + item,
        dataset="local-controls",
        split="dev",
        method="actual-validator",
        field="validity",
        **{"class": None},
        eligibility="eligible",
        status=status,
        correct=observed == expected if status == "ok" else None,
        predicted=observed if status == "ok" else None,
        expected=expected,
        human_touched_prediction=False,
        evidence_origin="synthetic",
        issues=(),
        ledger_refs=(),
    )


def spec():
    return MetricSpec(
        metric="accuracy",
        population="as_frozen",
        statistic_version="s9-structural-control.v1",
        denominator_policy="all-eligible.v1",
        zero_denominator_reason="zero_support",
        averaging="none",
    )


def test_actual_validator_positive_negative_feed_canonical_s2_reporting():
    rows = (outcome("valid", True), outcome("wrong-unit", False, unit="count"))
    statistic = accuracy(rows)
    assert (statistic.numerator, statistic.denominator, statistic.value) == (2, 2, 1)
    row = metric_row(
        rows,
        ("valid", "wrong-unit"),
        spec(),
        accuracy,
        method="actual-validator",
        dataset_alias="local-controls",
        split="dev",
        config_ref="test.v1",
        field="validity",
    )
    assert (row.corpus_N, row.eligible_N, row.answered_N, row.value) == (2, 2, 2, 1)
    counts = confusion_counts(rows, True)
    assert (counts.true_positive, counts.true_negative) == (1, 1)
    assert 0 < wilson_interval(2, 2)[0] < 1


def test_canonical_report_preserves_failure_population_and_refuses_dropped_case():
    rows = (outcome("valid", True), outcome("stale", True, status="stale"))
    row = metric_row(
        rows,
        ("valid", "stale"),
        spec(),
        accuracy,
        method="actual-validator",
        dataset_alias="local-controls",
        split="dev",
        config_ref="test.v1",
        field="validity",
    )
    assert (row.corpus_N, row.answered_N, row.stale_N, row.value) == (2, 1, 1, 0.5)
    with pytest.raises(ValueError, match="omitted/duplicated/unrequested"):
        metric_row(
            rows[:1],
            ("valid", "stale"),
            spec(),
            accuracy,
            method="actual-validator",
            dataset_alias="local-controls",
            split="dev",
            config_ref="test.v1",
            field="validity",
        )
