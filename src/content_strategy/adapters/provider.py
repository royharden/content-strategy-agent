"""Forward explicitly prepared offline calls to real S3 allocation/reuse checks."""

from ..pipeline.ports import CallBinding, PortRefusal
from ..shared.callledger.ledger import Ledger
from ..shared.callledger.models import Allocation, BudgetAuthority, CallContext, Limits
from ..shared.providers.controller import Provider
from ..shared.providers.models import GenerateRequest, Result, TypedJudgmentRequest


class OfflineGateway:
    """No capture creation, request registration, admission, retry or fallback here."""

    def __init__(self, provider: Provider):
        if type(provider) is not Provider or provider.mode not in {"mock", "strict_replay"}:
            raise PortRefusal("offline_provider_required")
        self.provider = provider

    def run(
        self, request: GenerateRequest | TypedJudgmentRequest, *, binding: CallBinding
    ) -> Result:
        expected = (
            (binding.ledger, Ledger),
            (binding.budget, BudgetAuthority),
            (binding.context, CallContext),
            (binding.limits, Limits),
            (binding.allocation, Allocation),
        )
        if any(type(value) is not kind for value, kind in expected):
            raise PortRefusal("actual_owner_binding_required")
        if binding.limits.max_outbound_attempts != 0:
            raise PortRefusal("offline_dispatch_forbidden")
        kwargs = dict(
            purpose=binding.purpose,
            ledger=binding.ledger,
            budget=binding.budget,
            context=binding.context,
            limits=binding.limits,
            allocation=binding.allocation,
        )
        self.provider.validate_replay_allocation(request, **kwargs)
        # Observation above is not a lease. Provider.run revalidates persisted allocation
        # before lookup, and S3 record_reuse rechecks atomically after a hit.
        return self.provider.run(request, **kwargs)
