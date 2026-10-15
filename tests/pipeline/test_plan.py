import json
from dataclasses import replace

import pytest

from content_strategy.pipeline.ports import (
    Bindings,
    GenerationResult,
    PortRefusal,
    SupportDecision,
    SupportResult,
    WorkflowPolicy,
)


def test_positive_metric_only_payload_explicit_mock_and_original_binding_objects(harness):
    h = harness
    bindings = h.bindings()
    result = h.port.plan(h.snapshot, "Suggest useful material", bindings=bindings)
    assert len(result.accepted) == result.proposed == 5 and not result.underfilled
    assert not result.dropped and result.repaired_proposals == 0
    assert all(value.origin == "mock" for value in result.accepted)
    payload = h.generate_calls[0][0].text
    assert "PRIVATE_POST_SENTINEL" not in payload
    assert "tag_provenance" not in payload and "rows" not in json.loads(payload)
    assert json.loads(payload)["requested_recommendations"] == {"minimum": 5, "maximum": 10}
    for assembly, binding in h.screen_calls + h.generate_calls:
        stage = binding.purpose.removeprefix("s9.")
        assert binding is bindings.get(stage, assembly.source_generation, h.policy)
    assert h.support_calls[0][2] is bindings.get(
        "support.initial", h.snapshot.snapshot_id, h.policy
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"decision": "needs_human"},
        {"coverage": "partial"},
        {"adapter_status": "unavailable"},
        {"input_sha256": "b" * 64},
        {"source_generation": "b" * 64},
        {"policy_sha256": "b" * 64},
        {"normalized_bytes": 32769},
        {"method": "typed_mock"},
        {"deterministic_flags": ("credential_request",), "diagnostic_notices": ("ordinary_word",)},
    ],
)
def test_any_initial_screen_hold_stale_partial_or_wrong_method_stops_generation(harness, overrides):
    h = harness
    h.screen_overrides = overrides
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and not h.generate_calls and not h.support_calls
    assert result.dropped


def test_notice_only_can_pass_but_never_removes_actual_flag(harness):
    h = harness
    h.screen_overrides = {"diagnostic_notices": ("quoted_word",)}
    assert len(h.port.plan(h.snapshot, "Brief", bindings=h.bindings()).accepted) == 5


def test_output_screen_hold_prevents_semantic_and_any_later_repair(harness):
    h = harness
    h.hold_support = True
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and len(h.generate_calls) == 1
    assert not h.support_calls and result.repaired_proposals == 0
    assert all(drop.codes == ("screen_hold",) for drop in result.dropped)


def test_whole_assembly_overflow_is_not_silently_trimmed_or_screened_as_prefix(harness):
    h = harness
    metrics = tuple(
        type(metric).model_validate(metric.model_dump() | {"definition": "z" * 16000})
        for metric in h.snapshot.metrics
    )
    snapshot = type(h.snapshot).model_validate(h.snapshot.model_dump() | {"metrics": metrics})
    result = h.port.plan(snapshot, "Brief", bindings=h.bindings())
    assert not h.screen_calls and not h.generate_calls and not result.accepted
    assert result.dropped[0].codes == ("input_too_large",)


def test_invalid_unicode_brief_fails_closed_before_any_port(harness):
    h = harness
    result = h.port.plan(h.snapshot, "\ud800", bindings=h.bindings())
    assert not result.accepted and not h.screen_calls
    assert result.dropped[0].codes == ("invalid_utf8_assembly",)


def test_invalid_unicode_generated_candidate_never_reaches_semantic_or_disclosure(harness):
    h = harness
    h.batches = [
        (h.candidate(text="\ud800 {{cite:er.x.topic.untagged}}"),),
        (h.candidate(text="\ud800 {{cite:er.x.topic.untagged}}"),),
    ]
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and not h.support_calls
    assert all(drop.codes == ("invalid_candidate_encoding",) for drop in result.dropped)


def test_one_content_repair_preserves_valids_and_reports_proposal_denominators(harness):
    h = harness
    h.batches = [
        tuple(h.candidate(word) for word in ("alpha", "bravo", "charlie", "delta"))
        + (h.candidate("bad", text="Unsupported 10% {{cite:er.x.topic.untagged}}"),),
        (h.candidate("echo"),),
    ]
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert len(result.accepted) == 5 and result.proposed == 6 and result.repaired_proposals == 1
    assert len(h.generate_calls) == 2
    repair = json.loads(h.generate_calls[1][0].text)
    assert repair["repair_errors"] == [{"codes": ["unsupported_numeric_grammar"]}]
    assert "Unsupported 10%" not in h.generate_calls[1][0].text
    assert result.dropped[0].codes == ("unsupported_numeric_grammar",)


@pytest.mark.parametrize("verdict", ["contradicts", "says_nothing", "unknown"])
def test_required_semantic_non_support_rejects_then_stops_after_one_repair(harness, verdict):
    h = harness
    h.semantic = verdict
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and result.underfilled
    assert len(h.generate_calls) == 2 and any(
        "semantic_" + verdict in drop.codes for drop in result.dropped
    )


def test_missing_semantic_answer_rejects_batch_and_does_not_disclose_bodies(harness):
    h = harness
    h.support_override = lambda items: SupportResult(
        status="ok", decisions=(), method="luna", origin="mock"
    )
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted
    assert all("alpha" not in str(value) for value in result.dropped)


def test_underfilled_result_is_visible_with_exact_survivors(harness):
    h = harness
    h.batches = [tuple(h.candidate(word) for word in ("alpha", "bravo", "charlie"))]
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert result.underfilled and len(result.accepted) == result.proposed == 3


def test_no_citable_metrics_returns_empty_without_ports_or_binding(harness):
    from content_strategy.ingest import Dataset
    from content_strategy.metrics import compute_metrics

    h = harness
    snapshot = compute_metrics(Dataset(h.dataset.rows[:1], "0" * 64)).snapshot
    result = h.port.plan(snapshot, "Brief", bindings=Bindings({}))
    assert not result.accepted and result.proposed == result.citable_total == 0
    assert not h.screen_calls and not h.generate_calls


@pytest.mark.parametrize(
    "fault",
    [
        "missing_future_stage",
        "wrong_context",
        "provider_repair",
        "bool_repair",
        "wrong_budget",
        "reused_child",
    ],
)
def test_whole_operation_preflight_refuses_before_first_port_call(harness, fault):
    h = harness
    original = h.bindings()
    stages = dict(original._stages)
    key = "support.repair"
    if fault == "missing_future_stage":
        del stages[key]
    elif fault == "wrong_context":
        stages[key].context.policy_sha256 = "b" * 64
    elif fault in {"provider_repair", "bool_repair"}:
        stages[key].limits.max_content_repairs = 1 if fault == "provider_repair" else False
    elif fault == "wrong_budget":
        stages[key] = replace(stages[key], budget=object())
    else:
        stages[key] = stages["support.initial"]
    with pytest.raises(PortRefusal):
        h.port.plan(h.snapshot, "Brief", bindings=Bindings(stages))
    assert not h.screen_calls and not h.generate_calls


def test_refusal_and_empty_result_are_honest_no_repairs_or_semantic_calls(harness):
    h = harness
    h.batches = [GenerationResult(status="refused", origin="mock")]
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and result.dropped[0].codes == ("generation_refused",)
    assert len(h.generate_calls) == 1 and not h.support_calls


def test_generation_cannot_relabel_mock_run_as_recorded_replay(harness):
    h = harness
    h.batches = [
        GenerationResult(
            status="ok",
            candidates=(h.candidate(),),
            origin="replay",
            model_reported="capture.model",
        )
    ]
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and not h.support_calls
    assert result.dropped[0].codes == ("generation_origin_mismatch",)


def test_semantic_origin_must_match_whole_execution(harness):
    h = harness
    h.support_override = lambda items: SupportResult(
        status="ok",
        decisions=tuple(
            SupportDecision(item_id=item.content.item.item_id, verdict="supports") for item in items
        ),
        method="jev",
        origin="replay",
    )
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and len(h.generate_calls) == 1


def test_live_policy_cannot_substitute_offline_rules():
    with pytest.raises(ValueError, match="execution_origin_method_mismatch"):
        WorkflowPolicy(screen_policy_sha256="a" * 64, required_method="rules", origin="live")


def test_unseen_metric_or_multi_scope_never_reaches_semantic_judge(harness):
    h = harness
    bad = h.candidate().model_copy(update={"scope": "multi"})
    h.batches = [(bad,), (bad,)]
    result = h.port.plan(h.snapshot, "Brief", bindings=h.bindings())
    assert not result.accepted and not h.support_calls
    assert "outside_metric_projection" in result.dropped[0].codes
