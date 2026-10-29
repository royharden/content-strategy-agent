"""Handcrafted contract controls only; never read original DEV/Gold/generator/heldout.

The in-memory custodian/comparator below is a test double, not an assertion of the
real corpus's unresolved reference-string or family-mapping semantics.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from content_strategy.evaluation.original_grounding import (
    SUPPORTS,
    CustodianAdmission,
    NeedsOwnerMetadata,
    OriginalGroundingMethod,
    evaluate,
    main,
)
from content_strategy.shared.evalkit.identity import canonical_bytes, ordered_ids_digest
from content_strategy.shared.evalkit.models import (
    Manifest,
    PinnedReference,
    PublicMethodInput,
    PublicProjectionPolicy,
    SourceRef,
    SplitEntry,
)
from content_strategy.shared.grounded.identity import identity_hash
from content_strategy.shared.grounded.models import Metric, MetricCitation
from content_strategy.shared.grounded.validation import EditorialLiteral, Policy, seal_content

GEN = "a" * 64
POLICY = Policy(screen_edition="handcrafted-source-only.v1")


def grounding_wire(category="valid_recommendation"):
    metric = Metric(
        metric_id="opaque-fact",
        snapshot_id=GEN,
        scope="x",
        definition="Handcrafted fact",
        value="0.1",
        unit="ratio",
        sample_size=5,
        computed_by="handcrafted",
        status="ok",
    )
    citation = MetricCitation(
        metric_id=metric.metric_id, snapshot_id=GEN, scope="x", quoted_value="0.1", unit="ratio"
    )
    fields = {
        "item_id": "original-content",
        "revision": 1,
        "kind": "recommendation",
        "scope": "x",
        "snapshot_id": GEN,
        "text": "Observed {{cite:opaque-fact}}",
        "citations": (citation,),
    }
    codes = []
    if category == "invalid_citation_unknown_id":
        fields.update(
            text="Observed {{cite:unknown}}",
            citations=(citation.model_copy(update={"metric_id": "unknown"}),),
        )
        codes = ["unknown_or_inaccessible_evidence"]
    elif category in {"invalid_citation_wrong_snapshot", "invalid_citation_wrong_platform"}:
        change = (
            {"snapshot_id": "b" * 64} if category.endswith("snapshot") else {"scope": "linkedin"}
        )
        fields["citations"] = (citation.model_copy(update=change),)
        codes = ["citation_generation_or_scope"]
    elif category in {"invalid_citation_wrong_value", "invalid_citation_wrong_unit"}:
        change = (
            {"quoted_value": "0.10000001"} if category.endswith("value") else {"unit": "percent"}
        )
        fields["citations"] = (MetricCitation.model_validate(citation.model_dump() | change),)
        codes = ["noncanonical_value_or_unit"]
    elif category == "invalid_citation_insufficient_n":
        metric = metric.model_copy(update={"sample_size": 4})
        codes = ["uncitable_evidence"]
    elif category == "invalid_citation_unavailable":
        metric = metric.model_copy(
            update={"status": "unavailable", "status_reason": "handcrafted", "value": None}
        )
        codes = ["uncitable_evidence", "noncanonical_value_or_unit"]
    elif category == "invalid_citation_empty_citation":
        fields.update(text="Proposed direction", citations=())
        codes = ["missing_citations"]
    elif category == "invalid_citation_conflicting_citation":
        fields["citations"] = (citation, citation)
        codes = ["duplicate_or_conflicting_citation"]
    elif category in {"invalid_citation_hidden_number", "invalid_disguised_performance_draft"}:
        fields["text"] += " tenfold"
        codes = ["unsupported_numeric_grammar"]
    if category in {"valid_editorial_draft", "invalid_disguised_performance_draft"}:
        fields.update(kind="draft", parent_id="parent", parent_revision=1)
    editorial = ()
    if category == "valid_editorial_draft":
        fields["text"] += "\n{{edit:cadence}}"
        editorial = (EditorialLiteral(name="cadence", role="cadence", value=3),)
    content = seal_content(**fields, editorial=editorial)
    wire = {
        "schema_version": "author-method-input.v1",
        "payload": {
            "task": "grounding",
            "content": content.model_dump(mode="json"),
            "metrics": [metric.model_dump(mode="json")],
            "current_generation": GEN,
            "policy": POLICY.model_dump(mode="json"),
        },
    }
    expected = {
        "kind": "grounding",
        "expected_valid": not codes,
        "expected_failure_classes": codes,
        "exact_reference_bindings": ["handcrafted-reference"],
    }
    return wire, expected


def public(wire):
    method = OriginalGroundingMethod(POLICY)
    from content_strategy.evaluation.original_grounding import VERSION

    return PublicMethodInput.model_validate_json(
        canonical_bytes(
            {
                "item_id": "original-case-id",
                "public_payload": wire,
                "input_sha256": identity_hash(wire),
                "public_config_refs": [VERSION, method.config_sha256],
            }
        )
    )


@pytest.mark.parametrize("category", tuple(SUPPORTS))
def test_original_wire_uses_real_validator_without_snapshot_or_remap(category):
    """what_bug_this_catches: original wire must work without inventing snapshot context."""
    wire, expected = grounding_wire(category)
    before = canonical_bytes(wire)
    result = OriginalGroundingMethod(POLICY).predict(public(wire))
    assert result.status == "ok" and result.machine_output is expected["expected_valid"]
    assert set(result.domain_payload["failure_codes"]) == set(expected["expected_failure_classes"])
    assert result.item_id == "original-case-id" and not result.domain_payload["producer_authority"]
    assert canonical_bytes(wire) == before


def test_ambiguous_metrics_and_bad_input_are_errors_not_correct_rejections():
    """what_bug_this_catches: malformed context cannot count as a correctly rejected example."""
    wire, _ = grounding_wire()
    wire["payload"]["metrics"] *= 2
    result = OriginalGroundingMethod(POLICY).predict(public(wire))
    assert result.status == "invalid" and result.machine_output is None


def test_cli_missing_owner_never_opens_any_path(monkeypatch, capsys):
    """what_bug_this_catches: absent owner metadata must refuse before protected IO."""
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("protected read occurred"))
    assert main(["--mode", "replay", "--split", "dev"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "needs_owner_metadata" and output["selected_required_N"] == 120


def write_ref(path, records):
    data = b"".join(canonical_bytes(record) + b"\n" for record in records)
    path.write_bytes(data)
    return PinnedReference(
        status="available", ref=str(path), sha256=hashlib.sha256(data).hexdigest()
    )


@pytest.fixture
def campaign(tmp_path):
    """Only ephemeral handcrafted contract material.

    Not a new shipped corpus or original generator.
    """
    methods, golds, pointers, selected, sources = [], [], [], [], {}
    category_map = {f"private-class-{i}": category for i, category in enumerate(SUPPORTS)}
    category_map["unselected"] = None
    categories = [
        (private, category)
        for private, category in category_map.items()
        if category is not None
        for _ in range(SUPPORTS[category])
    ]
    categories += [("unselected", None)] * 591
    for offset, (private, category) in enumerate(categories):
        fixture_id = f"opaque-{offset}"
        if category is None:
            wire = {
                "schema_version": "author-method-input.v1",
                "payload": {
                    "task": "tagging",
                    "request": {
                        "source_id": "handcrafted-source",
                        "text": "fixture",
                        "field": "topic",
                        "choices": ["workshop", "fieldwork", "reflection"],
                        "taxonomy_version": "author-synthetic-taxonomy.v1",
                    },
                },
            }
            expected = {
                "kind": "tagging",
                "expected_value": "workshop",
                "reference_ids": ["handcrafted-reference"],
                "abstention_allowed": False,
            }
        else:
            wire, expected = grounding_wire(category)
            selected.append(fixture_id)
            sources[fixture_id] = SourceRef(
                handle=f"explicit-original-locator-{offset}", sha256=identity_hash(wire)
            )
        methods.append(wire)
        golds.append(
            {
                "schema_version": "author-gold-input.v1",
                "fixture_id": fixture_id,
                "split": "dev",
                "method_input_sha256": identity_hash(wire),
                "private_source_family_ids": ["handcrafted-family"],
                "required_reference_ids": ["handcrafted-reference"],
                "contentGroundReferences": [],
                "what_bug_this_catches": "Handcrafted contract only",
                "label_provenance": "agent_provisional",
                "human_gold": False,
                "human_agreement_measured": False,
                "conflicts": [],
                "expected": expected,
                "unknown_required_reference_count": 0,
            }
        )
        pointers.append({"fixture_id": fixture_id, "category": private, "line_1based": offset + 1})
    method_ref = write_ref(tmp_path / "handcrafted-method.jsonl", methods)
    gold_ref = write_ref(tmp_path / "handcrafted-gold.jsonl", golds)
    index_ref = write_ref(tmp_path / "handcrafted-index.jsonl", pointers)
    comparator_ref = write_ref(
        tmp_path / "handcrafted-comparator.jsonl", [{"contract": "handcrafted-only"}]
    )
    ids = tuple(selected)
    manifest = Manifest(
        manifest_id="handcrafted-custodian-contract",
        parent_manifest_sha256=None,
        split_seed=1,
        partition_provenance="seeded",
        frozen_at="2026-01-02T00:00:00+00:00",
        scorer_version="handcrafted-only",
        comparator_config=comparator_ref,
        domain_adapter_ref=comparator_ref,
        experiment_refs={},
        splits=(
            SplitEntry(
                split="dev",
                items_file="not-a-rewritten-corpus.jsonl",
                item_count=120,
                ordered_item_ids=ids,
                items_sha256=gold_ref.sha256,
                ordered_ids_sha256=ordered_ids_digest(ids),
                group_ids=("handcrafted-group",),
            ),
        ),
        group_split_map={"handcrafted-group": "dev"},
        group_members={"handcrafted-group": ids},
        source_artifacts=(),
        publication_policy=PublicProjectionPolicy(
            mode="aggregate_only",
            allowed_dimensions=(),
            allowed_value_sets={},
            allowed_numeric_metrics=("value", "numerator", "denominator"),
            synthetic_example_refs=(),
        ),
        run_history_ref="handcrafted-no-heldout",
    )

    def compare_details(prediction, expected):
        # Explicit fake custodian comparator; original reference semantics remain unknown.
        return set(prediction.domain_payload["failure_codes"]) == set(
            expected["expected_failure_classes"]
        ) and expected["exact_reference_bindings"] == ["handcrafted-reference"]

    return CustodianAdmission(
        manifest=manifest,
        method_ref=method_ref,
        gold_ref=gold_ref,
        index_ref=index_ref,
        policy=POLICY,
        category_to_class=category_map,
        source_refs=sources,
        comparator_ref=comparator_ref,
        authorize=lambda: True,
        compare_details=compare_details,
        line_contract="same-physical-1based-no-blanks.v1",
        hash_contract="grounded-nfc-whole-method-no-newline.v1",
        parent_disposition="handcrafted-genesis",
    )


def rewrite(ref, change):
    records = [json.loads(line) for line in Path(ref.ref).read_bytes().splitlines()]
    change(records)
    return write_ref(Path(ref.ref), records)


def test_handcrafted_cli_positive_and_full_class_supports(campaign, capsys):
    """what_bug_this_catches: full positive/negative supports must pass without fake baselines."""
    assert main(["--mode", "replay", "--split", "dev"], admission=campaign) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["selected_N"] == 120 and output["unselected_not_run"] == 591
    assert {row["class"]: row["denominator"] for row in output["floors"]} == SUPPORTS
    assert all(row["numerator"] == row["denominator"] for row in output["floors"])
    assert "opaque-" not in json.dumps(output) and not output["producer_authority"]


@pytest.mark.parametrize(
    "missing",
    [
        "authorize",
        "compare_details",
        "line_contract",
        "hash_contract",
        "parent_disposition",
        "source_refs",
    ],
)
def test_missing_owner_contract_refuses_before_corpus_read(campaign, missing, monkeypatch):
    """what_bug_this_catches: missing metadata cannot be repaired by opening protected inputs."""
    value = (
        None
        if missing in {"authorize", "compare_details"}
        else {}
        if missing == "source_refs"
        else ""
    )
    changed = replace(campaign, **{missing: value})
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("protected read occurred"))
    with pytest.raises(NeedsOwnerMetadata):
        evaluate(changed)


@pytest.mark.parametrize("fault", ["line", "duplicate", "support", "zero"])
def test_index_join_and_support_failures_refuse_without_measurement(campaign, fault):
    """what_bug_this_catches: physical joins and duplicates cannot be skipped.

    Required populations cannot be skipped either.
    """

    def alter(records):
        if fault == "line":
            records[0]["line_1based"] = 2
        elif fault == "duplicate":
            records[1]["fixture_id"] = records[0]["fixture_id"]
        elif fault == "support":
            records[0]["category"] = records[6]["category"]
        else:
            for record in records:
                record["category"] = "unselected"

    changed = replace(campaign, index_ref=rewrite(campaign.index_ref, alter))
    with pytest.raises(ValueError):
        evaluate(changed)


@pytest.mark.parametrize("fault", ["blank", "bom", "duplicate-key", "file-hash", "pair-hash"])
def test_original_physical_json_and_hash_contracts_fail_closed(campaign, fault):
    """what_bug_this_catches: no blank skipping, hash fallback or permissive JSON last-wins."""
    if fault == "pair-hash":

        def alter(records):
            records[0]["method_input_sha256"] = "b" * 64

        changed = replace(campaign, gold_ref=rewrite(campaign.gold_ref, alter))
    else:
        path = Path(campaign.method_ref.ref)
        data = path.read_bytes()
        data = (
            b"\n" + data if fault == "blank" else b"\xef\xbb\xbf" + data if fault == "bom" else data
        )
        if fault == "duplicate-key":
            data = data.replace(b'{"payload":', b'{"schema_version":"wrong","payload":', 1)
        path.write_bytes(data)
        ref = campaign.method_ref.model_copy(update={"sha256": hashlib.sha256(data).hexdigest()})
        changed = replace(
            campaign,
            method_ref=ref if fault != "file-hash" else ref.model_copy(update={"sha256": "b" * 64}),
        )
    with pytest.raises(ValueError):
        evaluate(changed)


def test_method_error_is_retained_in_fixed_denominator(campaign):
    """what_bug_this_catches: malformed method inputs must fail their original class floor."""

    def alter(records):
        records[0]["payload"]["metrics"] *= 2

    method_ref = rewrite(campaign.method_ref, alter)
    digest = identity_hash(json.loads(Path(method_ref.ref).read_bytes().splitlines()[0]))

    def gold_change(records):
        records[0]["method_input_sha256"] = digest

    changed = replace(
        campaign, method_ref=method_ref, gold_ref=rewrite(campaign.gold_ref, gold_change)
    )
    outcomes, rows = evaluate(changed)
    assert len(outcomes) == 120 and outcomes[0].status == "invalid" and outcomes[0].correct is None
    assert rows[0].denominator == 6 and rows[0].numerator == 5 and rows[0].error_N == 1


def test_unknown_comparator_returns_metadata_requirement_not_floor_success(campaign):
    """what_bug_this_catches: unavailable reference semantics cannot be treated as agreement."""
    with pytest.raises(NeedsOwnerMetadata, match="failure_or_reference_comparator"):
        evaluate(replace(campaign, compare_details=lambda *args: None))
