"""Pure current payload construction; no dispatch, evidence, approval or truth authority."""

from collections import defaultdict, deque
from dataclasses import dataclass

from ..shared.grounded.identity import identity_hash
from ..shared.grounded.models import Metric, MetricSnapshot
from ..shared.grounded.validation import Checked, seal_content
from .ports import Candidate


def recommendation_id(candidate: Candidate) -> str:
    return "rec-" + identity_hash(candidate.model_dump(mode="python"))[:24]


def recommendation_content(candidate: Candidate, generation: str):
    """One sealing rule for the pipeline and its pre-admission authored compiler."""
    return seal_content(
        item_id=recommendation_id(candidate),
        revision=1,
        kind="recommendation",
        scope=candidate.scope,
        snapshot_id=generation,
        text=candidate.text,
        citations=candidate.citations,
        editorial=candidate.editorial,
    )


@dataclass(frozen=True)
class MetricProjection:
    citable: tuple[Metric, ...]
    selected: tuple[Metric, ...]

    def table(self) -> list[dict]:
        return [metric.model_dump(mode="python") for metric in self.selected]


def select_metrics(snapshot: MetricSnapshot, max_rows: int) -> MetricProjection:
    """The original declared round-robin selection, preserving exact sort/bin ordering."""
    citable = sorted(
        (
            metric
            for metric in snapshot.metrics
            if metric.status == "ok" and metric.sample_size >= 5
        ),
        key=lambda metric: metric.metric_id,
    )
    groups = defaultdict(deque)
    for metric in citable:
        dimension = (
            metric.metric_id.split(".")[2] if metric.metric_id.startswith("er.") else "trend"
        )
        groups[(metric.scope, dimension)].append(metric)
    selected = []
    while groups and len(selected) < max_rows:
        for key in sorted(tuple(groups)):
            selected.append(groups[key].popleft())
            if not groups[key]:
                del groups[key]
            if len(selected) == max_rows:
                break
    return MetricProjection(tuple(citable), tuple(selected))


def plan_document(brief: str, table: list[dict]) -> dict:
    return {
        "brief": brief,
        "metrics": table,
        "selection": "metric-projection.v1",
        "requested_recommendations": {"minimum": 5, "maximum": 10},
    }


def plan_support_document(pending: tuple[Checked, ...] | list[Checked], table: list[dict]) -> dict:
    return {
        "items": [
            {
                "item_id": value.content.item.item_id,
                "text": value.rendered,
                "citations": value.content.item.model_dump(mode="python")["citations"],
            }
            for value in pending
        ],
        "metrics": table,
    }


def draft_document(parent: Checked, snapshot: MetricSnapshot, brief: str) -> dict:
    content = parent.content
    keys = {citation.metric_id for citation in content.item.citations}
    return {
        "task": "draft",
        "brief": brief,
        "parent": parent.rendered,
        "scope": content.item.scope,
        "citations": content.item.model_dump(mode="python")["citations"],
        "metrics": [
            metric.model_dump(mode="python")
            for metric in snapshot.metrics
            if metric.metric_id in keys
        ],
        "requested_drafts": 1,
    }


def draft_support_document(checked: Checked, parent: Checked, document: dict) -> dict:
    return {
        "draft": checked.rendered,
        "parent": parent.rendered,
        "citations": document["citations"],
        "metrics": document["metrics"],
    }


def plan_repair_document(document: dict, codes) -> dict:
    return document | {"repair_errors": [{"codes": list(value)} for value in codes]}


def draft_repair_document(document: dict, codes) -> dict:
    return document | {"repair_errors": [list(value) for value in codes]}
