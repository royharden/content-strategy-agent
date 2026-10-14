"""Hand-calculated production-function oracles and mutation controls, no gold tuning."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal, Inexact, localcontext

import pytest

from content_strategy.ingest import Dataset, PostRow
from content_strategy.metrics import AnalysisConfig, compute_metrics

DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def row(identifier, impressions=10, likes=1, **changes):
    return replace(PostRow(identifier, DAY, "x", "body", impressions, likes, 0, 0), **changes)


def report(rows, clock="posted-local"):
    return compute_metrics(Dataset(tuple(rows), "0" * 64), AnalysisConfig(clock), created_at=NOW)


def one(result, dimension, key, *, family="rate", platform="x"):
    found = [
        c
        for c in result.computations
        if (c.dimension, c.key, c.family, c.metric.scope) == (dimension, key, family, platform)
    ]
    assert len(found) == 1
    return found[0]


def test_ratio_of_sums_positive_rows_not_average_and_zero_exclusion():
    rows = [
        row(f"p{i}", impressions=n, likes=k)
        for i, (n, k) in enumerate([(10, 10), (90, 0), (100, 10), (200, 0), (100, 30)])
    ]
    rows.append(row("excluded", impressions=0, likes=99999))
    result = report(rows)
    metric = one(result, "topic", "untagged")
    assert (metric.numerator, metric.denominator) == (50, 500)
    assert metric.metric.value == Decimal("0.1")  # Unweighted mean would be .28.
    assert metric.metric.status == "ok"
    assert (metric.metric.sample_size, metric.metric.excluded_size) == (5, 1)
    assert metric.excluded_ids == ("excluded",)
    assert metric.eligible_ids == tuple(f"p{i}" for i in range(5))
    assert result.platforms[0].missing_topic_rows == 6
    assert result.platforms[0].missing_format_rows == 6


def test_zero_engagement_valid_above_one_unclamped_and_all_interactions_count():
    for likes, expected in [(0, "0"), (20, "2")]:
        metric = one(report([row(str(i), likes=likes) for i in range(5)]), "topic", "untagged")
        assert metric.metric.status == "ok"
        assert metric.metric.value == Decimal(expected)
    metric = one(
        report([row(str(i), likes=1, comments=2, shares=3) for i in range(5)]), "topic", "untagged"
    )
    assert metric.metric.value == Decimal("0.6")


@pytest.mark.parametrize(("total", "expected"), [(1, "0"), (3, "0.00000002")])
def test_eight_place_half_even_independent_of_ambient_context(total, expected):
    rows = [row(str(i), impressions=40_000_000, likes=total if i == 0 else 0) for i in range(5)]
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_UP
        ambient.traps[Inexact] = True
        ambient.Emax = 2
        result = report(rows)
    assert one(result, "topic", "untagged").metric.value == Decimal(expected)


def test_extreme_counts_remain_eligible_exact_and_unavailable_distinct_from_zero():
    huge = 10**100
    result = report([row(str(i), impressions=1, likes=huge) for i in range(5)])
    metric = one(result, "topic", "untagged")
    assert metric.numerator == 5 * huge and metric.denominator == 5
    assert metric.metric.sample_size == 5 and metric.metric.excluded_size == 0
    assert metric.metric.status == "unavailable" and metric.metric.value is None
    assert metric.metric.status_reason == "arithmetic_out_of_range"
    zero = one(report([row(str(i), impressions=0) for i in range(5)]), "topic", "untagged")
    assert zero.metric.status_reason == "zero_eligible_impressions"
    assert zero.metric.sample_size == 0


def test_minimum_n_counts_only_positive_impressions_per_group():
    rows = [row("yes", topic="one")] + [
        row(f"zero{i}", impressions=0, topic="one") for i in range(4)
    ]
    metric = one(report(rows), "topic", "one").metric
    assert metric.status == "insufficient_data"
    assert metric.sample_size == 1 and metric.excluded_size == 4
    assert metric.value == Decimal("0.1")


def test_mixed_date_only_offset_and_clock_change_are_visible_and_fingerprinted():
    offset = datetime.fromisoformat("2026-10-11T23:30:00-02:00")
    rows = [row(f"timed{i}", date=offset) for i in range(5)] + [
        row(f"date{i}", date=date(2026, 10, 11)) for i in range(5)
    ]
    local, utc = report(rows), report(rows, "fixed-utc")
    assert one(local, "weekday", "sun").metric.sample_size == 10
    assert one(utc, "weekday", "mon").metric.sample_size == 5
    assert one(utc, "weekday", "sun").metric.sample_size == 5
    assert one(local, "hour", "23").metric.sample_size == 5
    assert one(utc, "hour", "1").metric.sample_size == 5
    assert local.platforms[0].missing_time_rows == 5
    assert local.platforms[0].eligible_hour_rows == 5
    assert (
        one(local, "hour", "missing_time", family="availability").metric.status_reason
        == "missing_time"
    )
    assert local.snapshot.snapshot_id != utc.snapshot.snapshot_id
    assert local.snapshot.identity.dataset_fingerprint == utc.snapshot.identity.dataset_fingerprint


def test_date_only_never_invents_an_hour_or_citable_hour():
    result = report([row(str(i)) for i in range(5)])
    assert not [c for c in result.computations if c.dimension == "hour" and c.family == "rate"]
    assert result.platforms[0].eligible_hour_rows == 0


@pytest.mark.parametrize(
    ("platform", "edges"),
    [("x", (0, 70, 140, 210)), ("linkedin", (0, 140, 500, 1500)), ("unknown", (0, 140, 500, 1500))],
)
def test_length_boundaries_and_all_four_bins(platform, edges):
    lengths = [edges[1] - 1, edges[1], edges[2], edges[3]]
    result = report(
        [row(f"p{i}", platform=platform, text="x" * length) for i, length in enumerate(lengths)]
    )
    expected = [
        f"{edges[0]}-{edges[1] - 1}",
        f"{edges[1]}-{edges[2] - 1}",
        f"{edges[2]}-{edges[3] - 1}",
        f"{edges[3]}+",
    ]
    assert [one(result, "length", key, platform=platform).eligible_ids for key in expected] == [
        ("p0",),
        ("p1",),
        ("p2",),
        ("p3",),
    ]


def test_nfc_length_empty_bins_and_supplied_slug_collisions():
    rows = [row(str(i), text="e\u0301" * 69, topic="A+B" if i < 3 else "A B") for i in range(5)]
    result = report(rows)
    assert one(result, "length", "0-69").metric.sample_size == 5
    assert one(result, "length", "70-139").metric.status_reason == "zero_eligible_impressions"
    ids = [one(result, "topic", key).metric.metric_id for key in ("A+B", "A B")]
    assert len(set(ids)) == 2 and all("a-b-" in identifier for identifier in ids)


def test_trend_inclusive_disjoint_windows_zero_prior_rate_and_outside_excluded():
    rows = [
        row(f"prior{i}", date=DAY - timedelta(days=days), likes=0)
        for i, days in enumerate((55, 28, 29, 30, 31))
    ]
    rows += [
        row(f"recent{i}", date=DAY - timedelta(days=days), likes=2)
        for i, days in enumerate((27, 0, 1, 2, 3))
    ]
    rows.append(row("outside", date=DAY - timedelta(days=56), likes=999999))
    trend = one(report(rows), "window", "recent_minus_prior_4w", family="trend")
    assert trend.metric.status == "ok" and trend.metric.value == Decimal("20")
    assert trend.metric.unit == "percentage_points" and trend.metric.sample_size == 5
    assert (trend.numerator, trend.denominator) == (50000, 2500)
    recent, prior = trend.windows
    assert (recent.start_ordinal, recent.end_ordinal) == (DAY.toordinal() - 27, DAY.toordinal())
    assert (prior.start_ordinal, prior.end_ordinal) == (DAY.toordinal() - 55, DAY.toordinal() - 28)
    assert set(recent.eligible_ids).isdisjoint(prior.eligible_ids)
    assert "outside" not in trend.eligible_ids


def test_trend_each_window_requires_five_and_latest_date_is_per_platform():
    rows = [
        row(f"prior{i}", date=DAY - timedelta(days=28), impressions=0 if i == 0 else 10)
        for i in range(5)
    ]
    rows += [row(f"recent{i}") for i in range(5)]
    rows += [row("future-other", platform="linkedin", date=DAY + timedelta(days=400))]
    trend = one(report(rows), "window", "recent_minus_prior_4w", family="trend")
    assert trend.metric.status == "insufficient_data" and trend.metric.sample_size == 4
    assert trend.metric.excluded_size == 1
    assert trend.windows[0].end_ordinal == DAY.toordinal()


def test_diagnostics_exact_ranking_ties_and_n_one_uncitable_status():
    rows = [row(f"p{i}", impressions=10, likes=i) for i in range(7)]
    result = report(rows)
    top = [c for c in result.computations if c.family == "diagnostic" and c.dimension == "top"]
    bottom = [
        c for c in result.computations if c.family == "diagnostic" and c.dimension == "bottom"
    ]
    assert [c.key for c in top] == ["p6", "p5", "p4", "p3", "p2"]
    assert [c.key for c in bottom] == ["p0", "p1", "p2", "p3", "p4"]
    assert all(
        c.metric.sample_size == 1 and c.metric.status == "insufficient_data" for c in top + bottom
    )
    tied = report([row("b"), row("a")])
    assert [
        c.key for c in tied.computations if c.family == "diagnostic" and c.dimension == "top"
    ] == ["a", "b"]
    exact = report([row("a", impressions=10**10, likes=1), row("b", impressions=10**10, likes=2)])
    assert [
        c.key for c in exact.computations if c.family == "diagnostic" and c.dimension == "top"
    ] == ["b", "a"]


def test_order_created_at_source_digest_invariant_config_and_tag_mutations_change_identity():
    rows = [row(str(i), text="PRIVATE_SOURCE_TEXT", topic="campaign") for i in range(5)]
    a, b = report(rows), report(list(reversed(rows)))
    assert a.snapshot.model_dump(mode="json") == b.snapshot.model_dump(mode="json")
    moved = compute_metrics(Dataset(tuple(rows), "1" * 64), created_at=NOW + timedelta(days=1))
    assert moved.snapshot.snapshot_id == a.snapshot.snapshot_id
    changed = report([replace(r, topic=None) for r in rows])
    assert changed.snapshot.snapshot_id != a.snapshot.snapshot_id
    assert "PRIVATE_SOURCE_TEXT" not in a.snapshot.model_dump_json()
    assert all(
        p.method == "supplied" for p in a.snapshot.identity.tag_provenance if p.field == "topic"
    )
    assert all(
        p.method == "missing"
        for p in changed.snapshot.identity.tag_provenance
        if p.field == "topic"
    )


def test_unknown_clock_rejects_and_calendar_underflow_is_explicit():
    with pytest.raises(ValueError, match="unsupported_analysis_clock"):
        AnalysisConfig("machine-local")
    with pytest.raises(ValueError, match="analysis_clock_out_of_calendar_range"):
        report([row("old", date=datetime.fromisoformat("0001-01-01T00:00:00+23:00"))], "fixed-utc")


def test_5000_max_count_rows_preserve_carry_and_normalized_serialization():
    maximum = 10**128 - 1
    result = report(
        [
            row(str(i), impressions=maximum, likes=maximum, comments=maximum, shares=maximum)
            for i in range(5000)
        ]
    )
    metric = one(result, "topic", "untagged")
    assert (metric.numerator, metric.denominator) == (15000 * maximum, 5000 * maximum)
    assert metric.metric.value == Decimal("3") and metric.metric.sample_size == 5000
    assert result.snapshot.model_dump_json()


def test_latest_zero_impression_date_still_anchors_trend_window():
    rows = [row(f"p{i}", date=DAY - timedelta(days=30)) for i in range(5)]
    rows.append(row("anchor", impressions=0, date=DAY))
    trend = one(report(rows), "window", "recent_minus_prior_4w", family="trend")
    assert trend.windows[0].end_ordinal == DAY.toordinal()
    assert trend.windows[0].eligible_ids == ()
    assert trend.metric.status_reason == "zero_eligible_impressions"
