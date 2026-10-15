"""Actual S3 accounting in D9's gateway; synthetic published fixture helpers only."""

import runpy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from content_strategy.adapters.provider import OfflineGateway
from content_strategy.pipeline.ports import CallBinding, PortRefusal
from content_strategy.shared.callledger.ledger import LedgerError
from content_strategy.shared.providers.captures import FixtureIndex
from content_strategy.shared.providers.controller import ProviderError


@pytest.fixture
def rig(tmp_path):
    # Exact published, namespace-adapted test helper; product never imports tests.
    helper = Path(__file__).resolve().parents[2] / (
        "conformance/vendor/s3/adapted/tests/providers/conftest.py"
    )
    return runpy.run_path(str(helper))["Rig"](tmp_path / "actual-ledger.sqlite3")


def admit(rig, provider, ledger):
    return provider.admit_operation(
        rig.plan(offline=True),
        ledger=ledger,
        budget=rig.authority,
        context=rig.context(),
        limits=rig.limits.model_copy(update={"max_outbound_attempts": 0}),
    )


def binding(rig, ledger, allocation):
    return CallBinding(**rig.kwargs(ledger, allocation, offline=True))


@pytest.mark.parametrize("mode", ["mock", "strict_replay"])
@pytest.mark.parametrize("hit", [True, False])
def test_real_allocation_hit_or_miss_never_dispatches_or_upgrades_origin(rig, mode, hit):
    fixtures = FixtureIndex([rig.capture()] if hit else [])
    provider = rig.provider(mode, fixtures=fixtures, capture_mode="fixture_replay")
    with rig.open(offline=True) as ledger:
        allocation = admit(rig, provider, ledger)
        result = OfflineGateway(provider).run(rig.request, binding=binding(rig, ledger, allocation))
        assert result.status == ("ok" if hit else "cache_miss")
        # A strict lookup miss carries backend origin, with no usable observation.
        assert result.origin == ("replay" if mode == "strict_replay" and not hit else "mock")
        assert result.current_external_cost_usd == "0" and result.attempt_ids == []
        assert ledger.totals()["dispatched_attempts"] == 0
        assert Decimal(ledger.totals()["known_spend_usd"]) == 0
        if hit:
            assert result.parsed == {"tier": "cheap"}
            assert result.source_capture.origin == "synthetic"
        else:
            assert result.parsed is None and result.source_capture is None


@pytest.mark.parametrize("mutation", ["generation", "purpose", "allocation", "request"])
def test_exact_request_context_and_allocation_fail_before_lookup(rig, mutation):
    provider = rig.provider(
        "strict_replay", fixtures=FixtureIndex([rig.capture()]), capture_mode="fixture_replay"
    )
    with rig.open(offline=True) as ledger:
        allocation = admit(rig, provider, ledger)
        bound = binding(rig, ledger, allocation)
        request = rig.request
        if mutation == "generation":
            bound = replace(
                bound, context=bound.context.model_copy(update={"source_generation": "g2"})
            )
        elif mutation == "purpose":
            bound = replace(bound, purpose="other-purpose")
        elif mutation == "allocation":
            bound = replace(
                bound, allocation=bound.allocation.model_copy(update={"operation_id": "missing"})
            )
        else:
            request = request.model_copy(update={"max_output_tokens": 31})
        with pytest.raises((ProviderError, LedgerError, ValueError)):
            OfflineGateway(provider).run(request, binding=bound)
        assert ledger.totals()["dispatched_attempts"] == 0


def test_rejects_simulated_dispatch_provider_and_non_owner_bindings(rig):
    with pytest.raises(PortRefusal, match="offline_provider_required"):
        OfflineGateway(rig.provider())
    provider = rig.provider("mock")
    with pytest.raises(PortRefusal, match="actual_owner_binding_required"):
        OfflineGateway(provider).run(
            rig.request, binding=CallBinding("x", None, None, None, None, None)
        )


def test_no_outbound_limit_widening_after_admission(rig):
    provider = rig.provider(
        "strict_replay", fixtures=FixtureIndex([]), capture_mode="fixture_replay"
    )
    with rig.open(offline=True) as ledger:
        allocation = admit(rig, provider, ledger)
        bound = binding(rig, ledger, allocation)
        bound = replace(bound, limits=bound.limits.model_copy(update={"max_outbound_attempts": 1}))
        with pytest.raises(PortRefusal, match="offline_dispatch_forbidden"):
            OfflineGateway(provider).run(rig.request, binding=bound)
        assert ledger.totals()["dispatched_attempts"] == 0
