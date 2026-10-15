"""Deterministic analytics, not recommendation, citation, approval or export authority."""

import hashlib
import json
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext
from fractions import Fraction
from typing import Literal

from ..ingest import INPUT_CONTRACT_VERSION, Dataset, PostRow
from ..shared.grounded import Metric, MetricSnapshot, SnapshotIdentity, TagProvenance, metric_slugs

COMPUTE_VERSION = "metrics.v1"
TAGGED_COMPUTE_VERSION = "metrics.v2-tagged"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
X_EDGES = (0, 70, 140, 210)
DEFAULT_EDGES = (0, 140, 500, 1500)


@dataclass(frozen=True)
class AnalysisConfig:
    clock: Literal["posted-local", "fixed-utc"] = "posted-local"

    def __post_init__(self):
        if self.clock not in {"posted-local", "fixed-utc"}:
            raise ValueError("unsupported_analysis_clock")

    def document(self) -> dict[str, object]:
        return {
            "edition": "metric-config.v1",
            "input_contract": INPUT_CONTRACT_VERSION,
            "clock": self.clock,
            "minimum_n": 5,
            "trend_weeks": 4,
            "decimal_precision": 28,
            "canonical_places": 8,
            "rounding": "ROUND_HALF_EVEN",
            "length_measure": "NFC_unicode_code_points",
            "length_edges": {"x": X_EDGES, "linkedin": DEFAULT_EDGES, "other": DEFAULT_EDGES},
        }


@dataclass(frozen=True)
class WindowDetail:
    start_ordinal: int
    end_ordinal: int
    eligible_ids: tuple[str, ...]
    numerator: int
    denominator: int


@dataclass(frozen=True)
class Computation:
    metric: Metric
    family: str
    dimension: str
    key: str
    eligible_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    numerator: int
    denominator: int
    windows: tuple[WindowDetail, ...] = ()


@dataclass(frozen=True)
class PlatformSummary:
    platform: str
    rows: int
    positive_impression_rows: int
    missing_time_rows: int
    eligible_hour_rows: int
    missing_topic_rows: int
    missing_format_rows: int


@dataclass(frozen=True)
class AnalyticsReport:
    snapshot: MetricSnapshot
    computations: tuple[Computation, ...]
    platforms: tuple[PlatformSummary, ...]


def _clock(row: PostRow, config: AnalysisConfig) -> tuple[date, int | None]:
    if isinstance(row.date, datetime):
        value = row.date
        if config.clock == "fixed-utc":
            try:
                value = value.astimezone(UTC)
            except (OverflowError, ValueError) as error:
                raise ValueError("analysis_clock_out_of_calendar_range") from error
        return value.date(), value.hour
    return row.date, None


def _value(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        try:
            return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.00000001"))
        except DecimalException:
            return None


def _sum(rows: tuple[PostRow, ...]) -> tuple[tuple[PostRow, ...], int, int]:
    eligible = tuple(row for row in rows if row.impressions > 0)
    return eligible, sum(row.interactions for row in eligible), sum(r.impressions for r in eligible)


def _bucket(row: PostRow) -> str:
    length = len(unicodedata.normalize("NFC", row.text))
    edges = X_EDGES if row.platform == "x" else DEFAULT_EDGES
    for start, stop in zip(edges, edges[1:], strict=False):
        if start <= length < stop:
            return f"{start}-{stop - 1}"
    return f"{edges[-1]}+"


def compute_metrics(
    dataset: Dataset,
    config: AnalysisConfig | None = None,
    *,
    created_at: datetime | None = None,
    tag_provenance: tuple[TagProvenance, ...] | None = None,
) -> AnalyticsReport:
    """Compute the complete local report; no source text is included in the metric table."""
    config = AnalysisConfig() if config is None else config
    if type(dataset) is not Dataset or type(config) is not AnalysisConfig:
        raise ValueError("validated_dataset_and_config_required")
    rows = tuple(sorted(dataset.rows, key=lambda row: row.post_id))
    compute_version = COMPUTE_VERSION
    if tag_provenance is not None:
        if type(tag_provenance) is not tuple or any(
            type(tag) is not TagProvenance for tag in tag_provenance
        ):
            raise ValueError("tag_provenance_records_tuple_required")
        tag_provenance = tuple(
            TagProvenance.model_validate(tag.model_dump(mode="python")) for tag in tag_provenance
        )
        expected = {(row.post_id, field) for row in rows for field in ("topic", "format")}
        keys = [(tag.source_id, tag.field) for tag in tag_provenance]
        if len(set(keys)) != len(keys) or set(keys) != expected:
            raise ValueError("full_unique_source_field_provenance_required")
        lookup = {(tag.source_id, tag.field): tag for tag in tag_provenance}
        assigned = []
        for row in rows:
            fields = {}
            for field in ("topic", "format"):
                tag = lookup[(row.post_id, field)]
                original = getattr(row, field)
                if original is not None:
                    if (
                        tag.value != original
                        or tag.method != "supplied"
                        or tag.model is not None
                        or tag.threshold is not None
                    ):
                        raise ValueError("supplied_tag_immutable")
                elif tag.method == "supplied":
                    raise ValueError("supplied_tag_absent_in_source")
                if (
                    tag.method == "missing" or tag.method.endswith("_abstained")
                ) and tag.value != "untagged":
                    raise ValueError("missing_tag_cannot_assign_label")
                fields[field] = None if original is None and tag.value == "untagged" else tag.value
            replacement = replace(row, **fields)
            if any(getattr(replacement, field) != value for field, value in fields.items()):
                raise ValueError("tag_label_not_canonical")
            assigned.append(replacement)
        rows = tuple(assigned)
        compute_version = TAGGED_COMPUTE_VERSION
    clocks = {row.post_id: _clock(row, config) for row in rows}
    tags = (
        tag_provenance
        if tag_provenance is not None
        else tuple(
            TagProvenance(
                source_id=row.post_id,
                field=field,
                value=getattr(row, field) or "untagged",
                method="supplied" if getattr(row, field) is not None else "missing",
                taxonomy_version="supplied-labels.v1",
            )
            for row in rows
            for field in ("topic", "format")
        )
    )
    identity = SnapshotIdentity(
        dataset_fingerprint=dataset.fingerprint,
        tag_provenance=tags,
        config_json=json.dumps(config.document()),
        compute_version=compute_version,
    )
    snapshot_id = identity.snapshot_id
    platform_slugs = metric_slugs(sorted({row.platform for row in rows}))
    computations: list[Computation] = []
    summaries = []

    def add(
        *,
        metric_id: str,
        scope: str,
        family: str,
        dimension: str,
        key: str,
        group: tuple[PostRow, ...],
        numerator: int | None = None,
        denominator: int | None = None,
        sample_size: int | None = None,
        windows: tuple[WindowDetail, ...] = (),
        forced_reason: str | None = None,
    ) -> None:
        eligible, n, d = _sum(group)
        n = n if numerator is None else numerator
        d = d if denominator is None else denominator
        count = len(eligible) if sample_size is None else sample_size
        value = _value(n, d)
        if forced_reason:
            status, reason, value = "unavailable", forced_reason, None
        elif d <= 0:
            status, reason = "unavailable", "zero_eligible_impressions"
        elif value is None:
            status, reason = "unavailable", "arithmetic_out_of_range"
        elif count < 5:
            status, reason = "insufficient_data", "minimum_eligible_n_5"
        else:
            status, reason = "ok", None
        unit = "percentage_points" if family == "trend" else "ratio"
        metric = Metric(
            metric_id=metric_id,
            snapshot_id=snapshot_id,
            scope=scope,
            definition=(
                f"{family};dimension={dimension};key={key};clock={config.clock};"
                "positive-impression distinct posts;minimum_n=5;"
                + ("sample_size=min(window eligible counts)" if windows else "ratio of sums")
            ),
            value=value,
            unit=unit,
            sample_size=count,
            excluded_size=len(group) - len(eligible),
            computed_by=f"{compute_version}.{family}",
            status=status,
            status_reason=reason,
        )
        computations.append(
            Computation(
                metric,
                family,
                dimension,
                key,
                tuple(r.post_id for r in eligible),
                tuple(r.post_id for r in group if r.impressions == 0),
                n,
                d,
                windows,
            )
        )

    for platform in sorted(platform_slugs):
        scope_rows = tuple(row for row in rows if row.platform == platform)
        prefix = platform_slugs[platform]
        missing_time = tuple(row for row in scope_rows if clocks[row.post_id][1] is None)
        summaries.append(
            PlatformSummary(
                platform,
                len(scope_rows),
                sum(row.impressions > 0 for row in scope_rows),
                len(missing_time),
                sum(
                    row.impressions > 0 and clocks[row.post_id][1] is not None for row in scope_rows
                ),
                sum(row.topic is None for row in scope_rows),
                sum(row.format is None for row in scope_rows),
            )
        )
        for dimension in ("topic", "format", "weekday", "hour", "length"):
            groups: dict[str, list[PostRow]] = defaultdict(list)
            if dimension == "length":
                edges = X_EDGES if platform == "x" else DEFAULT_EDGES
                for start, stop in zip(edges, edges[1:], strict=False):
                    groups[f"{start}-{stop - 1}"] = []
                groups[f"{edges[-1]}+"] = []
            for row in scope_rows:
                day, hour = clocks[row.post_id]
                if dimension == "hour" and hour is None:
                    continue
                key = (
                    (getattr(row, dimension) or "untagged")
                    if dimension in {"topic", "format"}
                    else WEEKDAYS[day.weekday()]
                    if dimension == "weekday"
                    else str(hour)
                    if dimension == "hour"
                    else _bucket(row)
                )
                groups[key].append(row)
            slugs = metric_slugs(sorted(groups))
            for key in sorted(groups):
                add(
                    metric_id=f"er.{prefix}.{dimension}.{slugs[key]}",
                    scope=platform,
                    family="rate",
                    dimension=dimension,
                    key=key,
                    group=tuple(groups[key]),
                )
            if dimension == "hour" and missing_time:
                add(
                    metric_id=f"unavailable.{prefix}.hour.missing-time",
                    scope=platform,
                    family="availability",
                    dimension="hour",
                    key="missing_time",
                    group=(),
                    forced_reason="missing_time",
                )

        eligible, _, _ = _sum(scope_rows)
        for rank_kind, direction in (("top", -1), ("bottom", 1)):
            ranked = sorted(
                eligible,
                key=lambda row: (
                    direction * Fraction(row.interactions, row.impressions),
                    row.post_id,
                ),
            )[:5]
            if not ranked:
                add(
                    metric_id=f"diagnostic.{prefix}.{rank_kind}.none",
                    scope=platform,
                    family="diagnostic",
                    dimension=rank_kind,
                    key="none",
                    group=(),
                    forced_reason="no_positive_impressions",
                )
            for row in ranked:
                slug = metric_slugs([row.post_id])[row.post_id][:48]
                suffix = hashlib.sha256(row.post_id.encode("utf-8")).hexdigest()[:16]
                add(
                    metric_id=f"diagnostic.{prefix}.{rank_kind}.{slug}-{suffix}",
                    scope=platform,
                    family="diagnostic",
                    dimension=rank_kind,
                    key=row.post_id,
                    group=(row,),
                )

        anchor = max(clocks[row.post_id][0].toordinal() for row in scope_rows)
        windows = []
        selected = []
        for start, end in ((anchor - 27, anchor), (anchor - 55, anchor - 28)):
            window_rows = tuple(
                row for row in scope_rows if start <= clocks[row.post_id][0].toordinal() <= end
            )
            positive, n, d = _sum(window_rows)
            selected.extend(window_rows)
            windows.append(WindowDetail(start, end, tuple(row.post_id for row in positive), n, d))
        recent, prior = windows
        add(
            metric_id=f"trend.{prefix}.overall.4w",
            scope=platform,
            family="trend",
            dimension="window",
            key="recent_minus_prior_4w",
            group=tuple(sorted(selected, key=lambda row: row.post_id)),
            numerator=100
            * (recent.numerator * prior.denominator - prior.numerator * recent.denominator),
            denominator=recent.denominator * prior.denominator,
            sample_size=min(len(recent.eligible_ids), len(prior.eligible_ids)),
            windows=tuple(windows),
        )
    snapshot = MetricSnapshot(
        identity=identity,
        snapshot_id=snapshot_id,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        metrics=tuple(computation.metric for computation in computations),
    )
    return AnalyticsReport(snapshot, tuple(computations), tuple(summaries))


__all__ = ["AnalysisConfig", "AnalyticsReport", "Computation", "PlatformSummary", "compute_metrics"]
