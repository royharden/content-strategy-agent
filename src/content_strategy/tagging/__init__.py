"""Minimal optional per-post tagging; supplied labels are never overwritten."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from ..ingest import Dataset
from ..pipeline import Pipeline
from ..pipeline.ports import Assembly, Bindings, TagPort, TagResult
from ..shared.grounded.identity import exact_decimal
from ..shared.grounded.models import TagProvenance

TAXONOMY = "tags.v1"
TOPICS = {
    "education": {"learn", "guide", "tutorial"},
    "product": {"launch", "release", "feature"},
    "community": {"community", "meetup", "together"},
}
FORMATS = {"text", "question", "list", "video"}


@dataclass(frozen=True)
class TagRun:
    source_fingerprint: str
    requested_method: str
    provenance: tuple[TagProvenance, ...]
    reasons: tuple[tuple[str, str], ...]


def compute_tagged_metrics(dataset: Dataset, run: TagRun, config=None, *, created_at=None):
    """Bind a task result to its original source before deriving a tagged snapshot."""
    from ..metrics import compute_metrics

    if type(run) is not TagRun or run.source_fingerprint != dataset.fingerprint:
        raise ValueError("stale_tag_source")
    return compute_metrics(dataset, config, created_at=created_at, tag_provenance=run.provenance)


def tag_dataset(
    dataset: Dataset,
    *,
    method: str,
    pipeline: Pipeline | None = None,
    tagger: TagPort | None = None,
    bindings: Bindings | None = None,
    threshold: Decimal | None = None,
) -> TagRun:
    if method not in {"supplied", "keyword", "untagged", "luna", "jev"}:
        raise ValueError("unknown_tag_method")
    typed = method in {"luna", "jev"}
    if typed and (
        not isinstance(threshold, Decimal) or not threshold.is_finite() or not 0 <= threshold <= 1
    ):
        raise ValueError("explicit_tag_threshold_required")
    if typed:
        threshold = exact_decimal(threshold)
    tags, reasons = [], []
    fingerprint = dataset.fingerprint
    global_failure = None
    if typed:
        if pipeline is None or tagger is None or bindings is None:
            global_failure = "tag_dependency_unavailable"
        else:
            try:
                bindings.require(
                    [
                        prefix + str(index)
                        for index, row in enumerate(
                            sorted(dataset.rows, key=lambda row: row.post_id)
                        )
                        if row.topic is None or row.format is None
                        for prefix in ("screen.tag.", "tag.")
                    ],
                    fingerprint,
                    pipeline.policy,
                )
            except Exception:
                global_failure = "tag_binding_unavailable"
    for index, row in enumerate(sorted(dataset.rows, key=lambda row: row.post_id)):
        choices, model, failure = {}, None, None
        if typed and (row.topic is None or row.format is None):
            if global_failure:
                failure = global_failure
            else:
                assembly = Assembly.build(
                    {
                        "text": row.text,
                        "taxonomy": {"topics": sorted(TOPICS), "formats": sorted(FORMATS)},
                    },
                    fingerprint,
                )
                try:
                    pipeline.screened(assembly, stage=f"screen.tag.{index}", bindings=bindings)
                    binding = bindings.get(f"tag.{index}", fingerprint, pipeline.policy)
                    result = TagResult.model_validate(
                        tagger.classify(assembly, binding=binding).model_dump()
                    )
                    if result.method != method:
                        raise ValueError("tag_method_mismatch")
                    model = result.model_reported
                    for field, allowed in (("topic", set(TOPICS)), ("format", FORMATS)):
                        choice = getattr(result, field)
                        if not 0 <= choice.confidence <= 1 or choice.value not in allowed:
                            raise ValueError("invalid_tag_choice")
                        if choice.confidence >= threshold:
                            choices[field] = choice.value
                except Exception:
                    choices, failure = {}, "tag_unavailable_or_held"
        elif method == "keyword":
            words = set(
                re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", row.text).casefold())
            )
            matches = [topic for topic, terms in TOPICS.items() if words.intersection(terms)]
            if len(matches) == 1:
                choices["topic"] = matches[0]
            choices["format"] = "question" if row.text.rstrip().endswith("?") else "text"
        for field in ("topic", "format"):
            supplied = getattr(row, field)
            value = supplied if supplied is not None else choices.get(field)
            source = (
                "supplied"
                if supplied is not None
                else method
                if value is not None
                else method + "_abstained"
            )
            tags.append(
                TagProvenance(
                    source_id=row.post_id,
                    field=field,
                    value=value or "untagged",
                    method=source,
                    model=model if supplied is None else None,
                    taxonomy_version=TAXONOMY,
                    threshold=threshold if typed and supplied is None else None,
                )
            )
            if value is None:
                reasons.append((row.post_id + ":" + field, failure or "unassigned"))
    return TagRun(fingerprint, method, tuple(tags), tuple(reasons))
