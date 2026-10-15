"""Actual S6/S3 calls through the app adapter, with synthetic offline evidence only."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from content_strategy.adapters.screening import NativeScreen
from content_strategy.pipeline.ports import Assembly, CallBinding, PortRefusal
from content_strategy.shared.providers.captures import FixtureIndex
from content_strategy.shared.providers.models import TypedJudgmentRequest
from content_strategy.shared.screen import ScreenPolicy, UntrustedText, prepare_text
from content_strategy.shared.screen.models import HAZARDS
from content_strategy.shared.screen.prepare import wrap_untrusted
from content_strategy.shared.screen.s3_adapter import TypedJudgmentRequest as ScreenRequestClass

PUBLIC = runpy.run_path(
    str(
        Path(__file__).resolve().parents[2]
        / "conformance/vendor/s3/adapted/tests/providers/conftest.py"
    )
)


class NativeRig(PUBLIC["Rig"]):
    def __init__(self, path, *, captured, hit=True):
        self._screen_policy = ScreenPolicy(
            "s9-native/1",
            "typed",
            profile_id="s9-synthetic-smoke/1",
            thresholds=dict.fromkeys(HAZARDS, 0.35),
            threshold_provenance="exploratory_seed",
        )
        self.assembly = Assembly("The label has the wrong color.", "a" * 64)
        prepared = prepare_text(
            UntrustedText("s9-complete-assembly", "a" * 64, self.assembly.text), self.screen_policy
        )
        self.native = NativeScreen.prepare(
            self.assembly,
            policy=self.screen_policy,
            model="fixture-model",
            captured_wrapped=wrap_untrusted(prepared) if captured else None,
        )
        super().__init__(path, flavor="typesafe", typed=True)
        # The public helper owns its price-policy attribute; S6 policy is retained separately.
        self.request = self.native.request
        self.evidence = []
        self.register(self.request)
        self.gateway = self.provider(
            "strict_replay" if captured else "mock",
            capture_mode="fixture_replay",
            fixtures=FixtureIndex([self.capture()] if hit else []),
        )
        self.ledger = self.open(offline=True)
        self.allocation = self.gateway.admit_operation(
            self.plan(offline=True),
            ledger=self.ledger,
            budget=self.authority,
            context=self.context(),
            limits=self.limits.model_copy(update={"max_outbound_attempts": 0}),
        )
        self.binding = CallBinding(**self.kwargs(self.ledger, self.allocation, offline=True))
        self.adapter = NativeScreen(self.native, provider=self.gateway, policy=self.screen_policy)

    @property
    def screen_policy(self):
        # Explicit synthetic policy, never derived from a paid price or tuning result.
        return self._screen_policy

    def context(self, *args, **kwargs):
        return (
            super()
            .context(*args, **kwargs)
            .model_copy(
                update={
                    "source_generation": "a" * 64,
                    "policy_sha256": self.screen_policy.sha256,
                }
            )
        )

    def body(self):
        return {
            "model": "fixture-model-reported",
            "answers": {key: {"type": "noul", "noul": 0.01} for key in HAZARDS},
            "usage": {"input_tokens": 100, "output_tokens": None},
        }


@pytest.fixture
def factory(tmp_path):
    rigs = []

    def create(**kwargs):
        rig = NativeRig(tmp_path / f"native-{len(rigs)}.sqlite3", **kwargs)
        rigs.append(rig)
        return rig

    yield create
    for rig in rigs:
        rig.ledger.close()


@pytest.mark.parametrize("captured", [False, True])
def test_same_canonical_classes_actual_admitted_native_hit_and_completed_reuse_hold(
    factory, captured
):
    assert ScreenRequestClass is TypedJudgmentRequest
    rig = factory(captured=captured)
    original = rig.native.request
    result = rig.adapter.check(rig.assembly, binding=rig.binding)
    assert rig.native.request is original
    assert result.method == "typed_mock" and result.decision == "pass"
    assert result.accounting_ref == rig.allocation.allocation_id
    assert result.input_sha256 == rig.assembly.digest
    assert rig.ledger.totals()["dispatched_attempts"] == 0
    with pytest.raises(PortRefusal, match="native_screen_hold"):
        rig.adapter.check(rig.assembly, binding=rig.binding)


def test_actual_native_miss_and_source_edit_hold_without_dispatch(factory):
    rig = factory(captured=True, hit=False)
    with pytest.raises(PortRefusal, match="native_screen_hold"):
        rig.adapter.check(rig.assembly, binding=rig.binding)
    assert rig.ledger.totals()["dispatched_attempts"] == 0
    rig = factory(captured=True)
    with pytest.raises(PortRefusal, match="native_screen_hold"):
        rig.adapter.check(
            replace(rig.assembly, text="Changed same generation"), binding=rig.binding
        )
    assert rig.ledger.totals()["dispatched_attempts"] == 0


@pytest.mark.parametrize("field", ["source_generation", "policy_sha256", "purpose"])
def test_actual_context_swap_refused_before_lookup(factory, field):
    rig = factory(captured=True)
    context = rig.binding.context.model_copy(update={field: "b" * 64})
    with pytest.raises(PortRefusal, match="native_screen_hold"):
        rig.adapter.check(rig.assembly, binding=replace(rig.binding, context=context))
    assert rig.ledger.totals()["dispatched_attempts"] == 0
