"""Explicit authored demo inputs, never a fixture-corpus/model/quality implementation."""

import csv
import io

from ..pipeline.assembly import recommendation_content, select_metrics
from ..pipeline.ports import Candidate
from ..shared.grounded.models import MetricCitation, MetricSnapshot


def demo_csv() -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(
        [
            "post_id",
            "date",
            "platform",
            "text",
            "impressions",
            "likes",
            "comments",
            "shares",
            "topic",
            "format",
        ]
    )
    for platform in ("linkedin", "x"):
        for index in range(12):
            day = "2026-09-01" if index < 6 else "2026-10-01"
            writer.writerow(
                [
                    f"demo-{platform}-{index}",
                    day + "T09:00:00-04:00",
                    platform,
                    "An explicitly synthetic workshop reflection.",
                    100 + index * 10,
                    5 + index,
                    2,
                    1,
                    "workshop",
                    "reflection",
                ]
            )
    return stream.getvalue().encode("utf-8")


def authored_plan_inputs(snapshot: MetricSnapshot):
    selected = select_metrics(snapshot, 40).selected
    if not selected:
        return (), {}
    phrases = (
        "Explore a practical lesson around this observed pattern",
        "Consider a reflection anchored in this observed pattern",
        "Share a concrete example related to this observed pattern",
        "Invite a discussion around this observed pattern",
        "Outline an experiment informed by this observed pattern",
    )
    candidates = []
    for index, phrase in enumerate(phrases):
        metric = selected[index % len(selected)]
        candidates.append(
            Candidate(
                scope=metric.scope,
                text=phrase + " {{cite:" + metric.metric_id + "}}",
                citations=(
                    MetricCitation(
                        snapshot_id=metric.snapshot_id,
                        metric_id=metric.metric_id,
                        scope=metric.scope,
                        quoted_value=metric.value,
                        unit=metric.unit,
                    ),
                ),
            )
        )
    values = tuple(candidates)
    return values, {
        recommendation_content(c, snapshot.snapshot_id).item.item_id: "supports" for c in values
    }


def authored_draft_input(parent):
    return Candidate(
        scope=parent.item.scope,
        text="A practical reflection to share. "
        + " ".join("{{cite:" + c.metric_id + "}}" for c in parent.item.citations),
        citations=parent.item.citations,
    )
