from datetime import date

import pytest

from content_strategy.ingest import Dataset, PostRow
from content_strategy.metrics import compute_metrics
from content_strategy.shared.grounded import TagProvenance
from content_strategy.tagging import compute_tagged_metrics, tag_dataset


def dataset(topic=None):
    return Dataset(
        tuple(
            PostRow(str(i), date(2026, 10, 14), "x", "guide", 10, 2, 0, 0, topic=topic)
            for i in range(5)
        ),
        "0" * 64,
    )


def tags(source, topic="education", method="keyword"):
    return tuple(
        TagProvenance(
            source_id=row.post_id,
            field=field,
            value=getattr(row, field) or (topic if field == "topic" else "text"),
            method="supplied" if getattr(row, field) is not None else method,
            taxonomy_version="tags.v1",
        )
        for row in source.rows
        for field in ("topic", "format")
    )


def test_tagged_grouping_preserves_original_fingerprint_and_binds_complete_provenance():
    source = dataset()
    original = source.fingerprint
    assignments = tags(source)
    report = compute_metrics(source, tag_provenance=assignments)
    assert source.fingerprint == report.snapshot.identity.dataset_fingerprint == original
    assert all(row.topic is None for row in source.rows)
    assert report.snapshot.identity.compute_version == "metrics.v2-tagged"
    metric = next(m for m in report.snapshot.metrics if m.metric_id == "er.x.topic.education")
    assert metric.sample_size == 5 and metric.status == "ok"
    changed = compute_metrics(source, tag_provenance=tags(source, "product"))
    assert changed.snapshot.snapshot_id != report.snapshot.snapshot_id
    assert changed.snapshot.identity.dataset_fingerprint == original
    reordered = compute_metrics(source, tag_provenance=tuple(reversed(assignments)))
    assert reordered.snapshot.snapshot_id == report.snapshot.snapshot_id


def test_real_keyword_tag_run_feeds_metrics_without_turning_inference_into_supplied():
    source = dataset()
    run = tag_dataset(source, method="keyword")
    report = compute_tagged_metrics(source, run)
    assert {tag.method for tag in report.snapshot.identity.tag_provenance} == {"keyword"}
    assert any(m.metric_id == "er.x.topic.education" for m in report.snapshot.metrics)
    assert report.platforms[0].missing_topic_rows == 0


def test_tag_run_cannot_be_reused_after_source_change_with_same_post_ids():
    from dataclasses import replace

    source = dataset()
    run = tag_dataset(source, method="keyword")
    changed = Dataset(tuple(replace(row, text="New source body") for row in source.rows), "0" * 64)
    with pytest.raises(ValueError, match="stale_tag_source"):
        compute_tagged_metrics(changed, run)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "unknown_source",
        "unknown_field",
        "whitespace_label",
        "false_supplied",
        "false_missing",
    ],
)
def test_incomplete_duplicate_unknown_or_false_tag_assignments_reject(mutation):
    source = dataset()
    assignments = list(tags(source))
    if mutation == "duplicate":
        assignments.append(assignments[0])
    elif mutation == "missing":
        assignments.pop()
    else:
        changes = {
            "unknown_source": {"source_id": "absent"},
            "unknown_field": {"field": "other"},
            "whitespace_label": {"value": " education "},
            "false_supplied": {"method": "supplied"},
            "false_missing": {"method": "keyword_abstained"},
        }
        assignments[0] = TagProvenance.model_validate(
            assignments[0].model_dump() | changes[mutation]
        )
    with pytest.raises(ValueError):
        compute_metrics(source, tag_provenance=tuple(assignments))


def test_supplied_source_labels_cannot_be_overwritten_or_relabelled_as_model_results():
    source = dataset("Supplied")
    assignments = tags(source)
    assert compute_metrics(source, tag_provenance=assignments).snapshot.metrics
    for changes in (
        {"value": "Other"},
        {"method": "jev"},
        {"model": "pretend"},
        {"threshold": "0.9"},
    ):
        altered = (
            TagProvenance.model_validate(assignments[0].model_dump() | changes),
        ) + assignments[1:]
        with pytest.raises(ValueError, match="supplied_tag_immutable"):
            compute_metrics(source, tag_provenance=altered)


def test_default_path_remains_original_version_and_missing_tags_stay_visible():
    source = dataset()
    report = compute_metrics(source)
    assert report.snapshot.identity.compute_version == "metrics.v1"
    assert report.platforms[0].missing_topic_rows == 5
    assert {tag.method for tag in report.snapshot.identity.tag_provenance} == {"missing"}
    run = tag_dataset(source, method="untagged")
    abstained = compute_metrics(source, tag_provenance=run.provenance)
    assert abstained.platforms[0].missing_topic_rows == 5


def test_threshold_or_method_provenance_changes_snapshot_without_raw_source_change():
    source = dataset()
    assignments = tags(source)
    first = compute_metrics(source, tag_provenance=assignments)
    changed = tuple(
        TagProvenance.model_validate(
            tag.model_dump() | {"method": "jev", "model": "fixture.model", "threshold": "0.9"}
        )
        for tag in assignments
    )
    second = compute_metrics(source, tag_provenance=changed)
    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id
    assert (
        first.snapshot.identity.dataset_fingerprint == second.snapshot.identity.dataset_fingerprint
    )
