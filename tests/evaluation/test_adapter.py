"""Source-only synthetic contract controls; no DEV, Gold, heldout or generator reads."""

import hashlib
import json
from copy import deepcopy

import pytest

from content_strategy.evaluation.adapter import VERSION, ReplayValidityAdapter
from content_strategy.ingest import ingest_csv
from content_strategy.metrics import AnalysisConfig, compute_metrics, source_default_tags
from content_strategy.shared.evalkit.identity import canonical_bytes, ordered_ids_digest
from content_strategy.shared.evalkit.models import (
    FieldLabel,
    FieldLabels,
    GoldRecord,
    Manifest,
    PinnedReference,
    SourceRef,
    SplitEntry,
)
from content_strategy.shared.evalkit.reporting import public_aggregate
from content_strategy.shared.evalkit.runner import MethodConfig, SourceView, compare
from content_strategy.shared.grounded.models import MetricCitation
from content_strategy.shared.grounded.validation import Content, Policy, seal_content


@pytest.fixture
def frame():
    # what_bug_this_catches: real source identity must accompany opaque replay IDs.
    csv = (
        "post_id,date,platform,text,impressions,likes,comments,shares,topic,format\n"
        + "".join(f"p{i},2026-01-01,x,synthetic,100,10,0,0,work,short\n" for i in range(5))
    ).encode()
    dataset = ingest_csv(csv)
    snapshot = compute_metrics(dataset).snapshot
    original = next(m for m in snapshot.metrics if m.scope == "x" and m.status == "ok")
    metric = original.model_copy(update={"metric_id": "opaque-rate"})
    content = seal_content(
        item_id="original-content-id",
        revision=1,
        kind="recommendation",
        scope="x",
        snapshot_id=snapshot.snapshot_id,
        text="Observed {{cite:opaque-rate}}",
        citations=(
            MetricCitation(
                snapshot_id=snapshot.snapshot_id,
                metric_id=metric.metric_id,
                scope="x",
                quoted_value=metric.value,
                unit=metric.unit,
            ),
        ),
    )
    source_hash = hashlib.sha256(csv).hexdigest()
    return {
        "content": content.model_dump(mode="json"),
        "metrics": [metric.model_dump(mode="json")],
        "public_contexts": [
            {
                "source": {
                    "media_type": "text/csv",
                    "csv_text": csv.decode(),
                    "original_byte_sha256": source_hash,
                },
                "config": json.loads(canonical_bytes(AnalysisConfig().document())),
                "tag_provenance": [t.model_dump(mode="json") for t in source_default_tags(dataset)],
            }
        ],
        "frozen_at": "2026-01-02T00:00:00+00:00",
        "source_ref": {"handle": "original-source-handle", "sha256": source_hash},
    }


@pytest.fixture
def adapter():
    return ReplayValidityAdapter(Policy(screen_edition="source-only-fixture.v1"))


def case(adapter, payload, expected=True, item_id="opaque-case-id"):
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    gold = GoldRecord(
        item_id=item_id,
        dataset="source-only-controls",
        group_id="scorer-private-group",
        split="dev",
        label_version="synthetic-reference.v1",
        source_ref=SourceRef.model_validate(payload["source_ref"]),
        input_sha256=digest,
        label_source="synthetic",
        label_provenance_ref=None,
        domain_kind=VERSION,
        label_payload=FieldLabels(
            kind="field_labels", labels={"validity": FieldLabel(presence="present", value=expected)}
        ),
    )
    adapter.validate_gold(gold)
    public = adapter.to_public_input(gold, SourceView("available", digest, payload))
    return gold, public


def mutate_content(payload, *, citation=None, **changes):
    content = Content.model_validate_json(canonical_bytes(payload["content"]))
    fields = content.item.model_dump(mode="python", exclude={"content_hash"})
    if citation is not None:
        fields["citations"] = (
            MetricCitation.model_validate(content.item.citations[0].model_dump() | citation),
        )
    fields.update(changes)
    payload["content"] = seal_content(**fields).model_dump(mode="json")


def test_real_validator_positive_preserves_ids_values_and_unprivileged_origin(adapter, frame):
    """what_bug_this_catches: replay binding must not remap IDs or mint producer authority."""
    original = deepcopy(frame)
    gold, public = case(adapter, frame)
    prediction = adapter.predict(public)
    adapter.validate_prediction(prediction)
    assert prediction.item_id == gold.item_id == "opaque-case-id"
    assert prediction.status == "ok" and prediction.machine_output is True
    assert prediction.domain_payload["producer_authority"] is False
    assert prediction.domain_payload["evidence_origin"] == "authored_synthetic_replay"
    assert prediction.source_refs == (gold.source_ref,)
    assert frame == original and public.public_payload == original
    assert public.public_payload["content"]["item"]["item_id"] == "original-content-id"
    assert adapter.to_outcomes(prediction, gold, adapter.policy)[0].correct is True


@pytest.mark.parametrize(
    "mutation",
    [
        "value",
        "unit",
        "unknown",
        "citation-generation",
        "platform",
        "missing",
        "number",
        "low-n",
        "unavailable",
        "duplicate",
    ],
)
def test_production_validator_rejects_declared_invalid_cases(adapter, frame, mutation):
    """what_bug_this_catches: execute actual validation, preserving negative controls."""
    if mutation == "value":
        mutate_content(frame, citation={"quoted_value": "0.10000001"})
    elif mutation == "unit":
        mutate_content(frame, citation={"unit": "wrong-unit"})
    elif mutation == "unknown":
        mutate_content(frame, citation={"metric_id": "missing"}, text="{{cite:missing}}")
    elif mutation == "citation-generation":
        mutate_content(frame, citation={"snapshot_id": "b" * 64})
    elif mutation == "platform":
        mutate_content(frame, citation={"scope": "linkedin"})
    elif mutation == "missing":
        mutate_content(frame, citations=())
    elif mutation == "number":
        mutate_content(frame, text="Ten times {{cite:opaque-rate}}")
    elif mutation == "low-n":
        frame["metrics"][0]["sample_size"] = 4
    elif mutation == "unavailable":
        frame["metrics"][0].update(status="unavailable", status_reason="synthetic", value=None)
    elif mutation == "duplicate":
        content = Content.model_validate_json(canonical_bytes(frame["content"]))
        mutate_content(frame, citations=content.item.citations * 2)
    gold, public = case(adapter, frame, expected=False)
    prediction = adapter.predict(public)
    assert prediction.status == "ok" and prediction.machine_output is False
    assert prediction.domain_payload["failure_codes"]
    assert adapter.to_outcomes(prediction, gold, adapter.policy)[0].correct is True


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "sha", "generation", "metrics"])
def test_invalid_binding_is_error_not_successful_rejection(adapter, frame, mutation):
    """what_bug_this_catches: missing identity cannot count as a successful rejection."""
    if mutation == "missing":
        frame["public_contexts"] = []
    elif mutation == "duplicate":
        frame["public_contexts"] *= 2
    elif mutation == "sha":
        frame["public_contexts"][0]["source"]["original_byte_sha256"] = "b" * 64
    elif mutation == "generation":
        frame["metrics"][0]["snapshot_id"] = "b" * 64
    elif mutation == "metrics":
        frame["metrics"] *= 2
    gold, public = case(adapter, frame, expected=False)
    prediction = adapter.predict(public)
    outcome = adapter.to_outcomes(prediction, gold, adapter.policy)[0]
    assert prediction.status == outcome.status == "invalid"
    assert outcome.correct is None and outcome.predicted is None
    row = adapter.report((outcome,), (gold.item_id,), dataset_alias="synthetic", split="dev")
    assert (row.numerator, row.denominator, row.error_N, row.value) == (0, 1, 1, 0)


def test_gold_is_scorer_only_and_never_changes_public_method_inputs(adapter, frame):
    """what_bug_this_catches: swapping scorer labels/group cannot change prediction input."""
    gold, public = case(adapter, frame)
    changed = gold.model_copy(
        update={
            "group_id": "other-scorer-private-group",
            "label_payload": FieldLabels(
                kind="field_labels",
                labels={"validity": FieldLabel(presence="present", value=False)},
            ),
        }
    )
    second = adapter.to_public_input(changed, SourceView("available", gold.input_sha256, frame))
    assert second == public
    prediction = adapter.predict(public)
    assert adapter.to_outcomes(prediction, gold, adapter.policy)[0].correct is True
    assert adapter.to_outcomes(prediction, changed, adapter.policy)[0].correct is False
    assert "scorer-private-group" not in canonical_bytes(public.model_dump(mode="json")).decode()


@pytest.mark.parametrize("key", ["gold", "label_payload", "group_id", "expected", "hidden_rubric"])
def test_nested_scorer_metadata_is_refused_before_method_input(adapter, frame, key):
    """what_bug_this_catches: nested labels must not leak through a broad payload copy."""
    frame["content"][key] = "private"
    with pytest.raises(ValueError, match="scorer_metadata_in_public_input"):
        case(adapter, frame)


def test_source_config_and_case_bindings_cannot_be_relabelled(adapter, frame):
    """what_bug_this_catches: bind public input to its exact admitted bytes and config."""
    gold, public = case(adapter, frame)
    for changed in (
        public.model_copy(update={"input_sha256": "b" * 64}),
        public.model_copy(update={"public_config_refs": ("other",)}),
    ):
        assert adapter.predict(changed).status == "invalid"
    with pytest.raises(ValueError, match="public_source_identity_changed"):
        adapter.to_public_input(gold, SourceView("stale", gold.input_sha256, frame))
    with pytest.raises(ValueError, match="scorer_identity_or_policy_changed"):
        adapter.to_outcomes(
            adapter.predict(public), gold.model_copy(update={"item_id": "other"}), adapter.policy
        )
    forged = adapter.predict(public).model_copy(
        update={"source_refs": (gold.source_ref.model_copy(update={"handle": "remapped"}),)}
    )
    with pytest.raises(ValueError, match="scorer_identity_or_policy_changed"):
        adapter.to_outcomes(forged, gold, adapter.policy)


def test_mixed_report_keeps_error_denominator_and_cannot_pass_reject_all(adapter, frame):
    """what_bug_this_catches: reject-all and dropped errors must not look like a perfect floor."""
    rows = []
    for index, kind in enumerate(("positive", "negative", "error")):
        payload = deepcopy(frame)
        if kind == "negative":
            mutate_content(payload, citation={"unit": "wrong-unit"})
        elif kind == "error":
            payload["public_contexts"] = []
        gold, public = case(adapter, payload, expected=kind == "positive", item_id=f"case-{index}")
        rows.extend(adapter.to_outcomes(adapter.predict(public), gold, adapter.policy))
    expected_ids = tuple(row.item_id for row in rows)
    report = adapter.report(tuple(rows), expected_ids, dataset_alias="synthetic", split="dev")
    assert (report.numerator, report.denominator, report.corpus_N, report.error_N) == (2, 3, 3, 1)
    projection = public_aggregate(report, adapter.public_projection_policy())
    assert set(projection) == {"value", "numerator", "denominator", "corpus_N", "error_N"}
    with pytest.raises(ValueError, match="omitted/duplicated/unrequested"):
        adapter.report(tuple(rows[:2]), expected_ids, dataset_alias="synthetic", split="dev")
    reject_all = tuple(
        row.model_copy(update={"predicted": False, "correct": row.expected is False})
        if row.status == "ok"
        else row
        for row in rows
    )
    assert (
        adapter.report(reject_all, expected_ids, dataset_alias="synthetic", split="dev").value < 1
    )


@pytest.mark.parametrize(
    "change", [{"producer_authority": True}, {"valid": "false"}, {"failure_codes": []}]
)
def test_prediction_provenance_and_output_contract_are_checked(adapter, frame, change):
    """what_bug_this_catches: forged authority or contradictory validity output cannot be scored."""
    mutate_content(frame, citation={"unit": "wrong-unit"})
    gold, public = case(adapter, frame, expected=False)
    prediction = adapter.predict(public)
    forged = prediction.model_copy(update={"domain_payload": prediction.domain_payload | change})
    with pytest.raises(ValueError, match="invalid_validity_prediction"):
        adapter.to_outcomes(forged, gold, adapter.policy)


@pytest.mark.parametrize("source_status", ["available", "stale", "unavailable"])
def test_actual_evalkit_compare_preserves_fixed_cases_and_source_refusals(
    adapter, frame, source_status
):
    """what_bug_this_catches: actual generic engine must retain refused cases, not drop them."""
    records, views = [], {}
    for index in range(2):
        payload = deepcopy(frame)
        if index:
            mutate_content(payload, citation={"unit": "wrong-unit"})
        gold, public = case(adapter, payload, expected=not index, item_id=f"case-{index}")
        records.append(gold)
        views[gold.item_id] = SourceView(
            source_status if index else "available", gold.input_sha256, public.public_payload
        )
    ids = tuple(record.item_id for record in records)
    pin = PinnedReference(status="available", ref="synthetic-contract", sha256="a" * 64)
    manifest = Manifest(
        manifest_id="in-memory-source-only-control",
        parent_manifest_sha256=None,
        split_seed=1,
        partition_provenance="seeded",
        frozen_at="2026-01-02T00:00:00+00:00",
        scorer_version=VERSION,
        comparator_config=pin,
        domain_adapter_ref=pin,
        experiment_refs={},
        splits=(
            SplitEntry(
                split="dev",
                items_file="synthetic-not-read.jsonl",
                item_count=2,
                ordered_item_ids=ids,
                items_sha256=hashlib.sha256(
                    canonical_bytes([record.model_dump(mode="json") for record in records])
                ).hexdigest(),
                ordered_ids_sha256=ordered_ids_digest(ids),
                group_ids=("scorer-private-group",),
            ),
        ),
        group_split_map={"scorer-private-group": "dev"},
        group_members={"scorer-private-group": ids},
        source_artifacts=(),
        publication_policy=adapter.public_projection_policy(),
        run_history_ref="in-memory-control-only",
    )
    result = compare(
        {adapter.method: MethodConfig(VERSION, adapter.config_sha256, "synthetic", adapter)},
        manifest,
        "dev",
        tuple(records),
        adapter,
        adapter.policy,
        lambda gold: views[gold.item_id],
    )
    actual = result.methods[adapter.method]
    assert actual.requested_item_ids == ids
    assert tuple(row.item_id for row in actual.outcomes) == ids
    report = adapter.report(actual.outcomes, ids, dataset_alias="synthetic", split="dev")
    assert report.denominator == 2
    assert report.numerator == (2 if source_status == "available" else 1)
    assert actual.outcomes[1].status == ("ok" if source_status == "available" else source_status)
