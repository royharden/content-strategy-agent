"""Actual S3/S6 application mock path, with synthetic answers and no fixture corpus."""

from dataclasses import replace

import pytest

from content_strategy.ingest import ingest_csv
from content_strategy.metrics import compute_metrics
from content_strategy.pipeline.assembly import recommendation_content
from content_strategy.pipeline.ports import Candidate, PortRefusal
from content_strategy.runtime.mock import compile_plan
from content_strategy.shared.grounded.models import MetricCitation
from content_strategy.shared.providers.captures import FixtureIndex
from content_strategy.shared.screen import ScreenPolicy
from content_strategy.shared.screen.models import HAZARDS


@pytest.fixture
def make(tmp_path):
    payload = b"post_id,date,platform,text,impressions,likes,comments,shares\n" + b"".join(
        f"p{i},2026-01-01,linkedin,source,10,2,0,0\n".encode() for i in range(5)
    )
    snapshot = compute_metrics(ingest_csv(payload)).snapshot
    candidates = tuple(
        Candidate(
            scope="linkedin",
            text=word + " {{cite:er.linkedin.topic.untagged}}",
            citations=(
                MetricCitation(
                    snapshot_id=snapshot.snapshot_id,
                    metric_id="er.linkedin.topic.untagged",
                    scope="linkedin",
                    quoted_value="0.2",
                    unit="ratio",
                ),
            ),
        )
        for word in ("alpha", "bravo", "charlie", "delta", "echo")
    )
    support = {
        recommendation_content(c, snapshot.snapshot_id).item.item_id: "supports" for c in candidates
    }
    policy = ScreenPolicy(
        "s9-test-authored.v1",
        "typed",
        profile_id="s9-synthetic-smoke.v1",
        thresholds=dict.fromkeys(HAZARDS, 0.35),
        threshold_provenance="exploratory_seed",
    )
    runtimes = []

    def create(verdict="supports", **changes):
        kwargs = dict(
            namespace="s9-development",
            screen_policy=policy,
            screen_scores=dict.fromkeys(HAZARDS, 0.01),
            support_verdicts=dict.fromkeys(support, verdict),
        )
        kwargs.update(changes)
        runtime = compile_plan(
            tmp_path / f"plan-{len(runtimes)}.sqlite3",
            snapshot,
            "An authored content plan",
            candidates,
            **kwargs,
        )
        runtimes.append(runtime)
        return runtime

    yield create
    for runtime in runtimes:
        runtime.close()


def test_complete_actual_four_stage_plan_same_allocation_original_nonce_and_zero_dispatch(make):
    runtime = make()
    native = tuple(adapter.request.request for _, adapter in runtime.ports.screens.values())
    strategy = runtime.run()
    assert len(strategy.accepted) == 5 and not strategy.underfilled
    assert strategy.proposed == 5 and strategy.repaired_proposals == 0 and not strategy.dropped
    assert all(
        value.screen.method == "typed_mock" and value.origin == "mock"
        for value in strategy.accepted
    )
    assert all(
        value.screen.accounting_ref == runtime.allocation.allocation_id
        for value in strategy.accepted
    )
    assert native == tuple(adapter.request.request for _, adapter in runtime.ports.screens.values())
    assert len(runtime.ports.completed) == 4
    assert len(runtime.cleanup) == 4 and all(state == "skipped" for _, state in runtime.cleanup)
    for result in runtime.ports.results:
        assert result.origin == "mock" and result.current_external_cost_usd == "0"
        assert result.accounting_ref == runtime.allocation.allocation_id
        assert result.source_capture.origin == "synthetic"
        assert result.normalized_usage.input_tokens is None
    assert runtime.ledger.totals()["dispatched_attempts"] == 0
    assert runtime.ledger.operation_state(runtime.allocation) != "pending"
    calls = list(runtime.ports.calls.values()) + [c for c, _ in runtime.ports.screens.values()]
    for call in calls:
        assert call.binding.ledger is runtime.ledger
        assert call.binding.allocation is runtime.allocation
        assert call.binding.budget is calls[0].binding.budget
        assert call.binding.limits is calls[0].binding.limits
    with pytest.raises(PortRefusal, match="already_used"):
        runtime.run()


@pytest.mark.parametrize("change", ["assembly", "generation", "context", "allocation", "unknown"])
def test_unknown_or_edited_input_refuses_before_actual_lookup(make, change):
    runtime = make()
    call = runtime.ports.calls["s9.plan.initial"]
    assembly, binding = call.assembly, call.binding
    if change == "assembly":
        assembly = replace(assembly, text=assembly.text + " ")
    elif change == "generation":
        assembly = replace(assembly, source_generation="a" * 64)
    elif change == "context":
        binding = replace(
            binding, context=binding.context.model_copy(update={"source_generation": "a" * 64})
        )
    elif change == "allocation":
        binding = replace(binding, allocation=binding.allocation.model_copy())
    elif change == "unknown":
        binding = replace(binding, purpose="s9.plan.repair")

    class NoLookup:
        def lookup(self, *args, **kwargs):
            pytest.fail("edited input reached fixture lookup")

    call.gateway.provider.fixtures = NoLookup()
    with pytest.raises(PortRefusal):
        runtime.ports.generate(assembly, binding=binding)
    assert runtime.ledger.totals()["dispatched_attempts"] == 0


@pytest.mark.parametrize("kind", ["capture_miss", "hazard", "support_contradicts"])
def test_actual_holds_do_not_become_success_or_dispatch(make, kind):
    changes = {}
    if kind == "hazard":
        changes["screen_scores"] = dict.fromkeys(HAZARDS, 0.9)
    runtime = make(
        verdict="contradicts" if kind == "support_contradicts" else "supports", **changes
    )
    if kind == "capture_miss":
        for call, _ in runtime.ports.screens.values():
            call.gateway.provider.fixtures = FixtureIndex([])
    strategy = runtime.run()
    assert not strategy.accepted and strategy.underfilled and strategy.dropped
    assert runtime.ledger.totals()["dispatched_attempts"] == 0


def test_missing_screen_answer_refuses_before_database_creation(make):
    with pytest.raises(PortRefusal, match="complete_authored_screen_answers"):
        make(screen_scores={})


def test_nested_original_request_edit_cannot_hit_an_existing_capture(make):
    runtime = make()
    call = runtime.ports.calls["s9.plan.initial"]
    call.request.messages[0].content.append(call.request.messages[0].content[0])

    class NoLookup:
        def lookup(self, *args, **kwargs):
            pytest.fail("unregistered request reached fixture lookup")

    call.gateway.provider.fixtures = NoLookup()
    with pytest.raises(ValueError):
        runtime.ports.generate(call.assembly, binding=call.binding)
    assert runtime.ledger.totals()["dispatched_attempts"] == 0
