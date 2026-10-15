"""Project a complete S6 rules result without upgrading its method or authority."""

from ..pipeline.ports import Assembly, CallBinding, PortRefusal, ScreenVerdict
from ..shared.providers.controller import Provider
from ..shared.screen import PreparedText, ScreenPolicy, UntrustedText, prepare_text, screen_rules
from ..shared.screen.s3_adapter import (
    ScreenRequestBinding,
    bind_native_request,
    native_binding_permits_model_input,
)
from ..shared.screen.typed import screen_typed


class RulesScreen:
    def __init__(self, policy: ScreenPolicy):
        if type(policy) is not ScreenPolicy or policy.required_method != "rules":
            raise PortRefusal("rules_policy_required")
        self.policy = policy

    def check(self, assembly: Assembly, *, binding: CallBinding) -> ScreenVerdict:
        if assembly.source_generation != getattr(binding.context, "source_generation", None):
            raise PortRefusal("screen_generation_mismatch")
        source = UntrustedText("s9-complete-assembly", assembly.source_generation, assembly.text)
        prepared = prepare_text(source, self.policy)
        if not isinstance(prepared, PreparedText):
            raise PortRefusal("screen_input_unavailable")
        result = screen_rules(source, self.policy)
        if result.decision == "pass" and not result.permits_model_input(source, self.policy):
            raise PortRefusal("screen_binding_invalid")
        return ScreenVerdict(
            input_sha256=result.input_sha256,
            normalized_sha256=result.normalized_sha256,
            source_generation=result.source_generation,
            policy_sha256=result.policy_sha256,
            transform_version=result.transform_version,
            method=result.method,
            coverage=result.coverage,
            normalized_bytes=prepared.normalized_byte_length,
            decision=result.decision,
            deterministic_flags=result.deterministic_flags,
            diagnostic_notices=result.diagnostic_notices,
            adapter_status="ok",
        )


class NativeScreen:
    """One prepared S6 request, externally admitted by the caller before use.

    This adapter never registers request evidence, creates a ledger/allocation, rebuilds
    a capture nonce or persists a screening result. The host must recheck current source
    under its write transaction before retaining any downstream content.
    """

    @staticmethod
    def prepare(assembly: Assembly, *, policy: ScreenPolicy, model: str, captured_wrapped=None):
        if type(policy) is not ScreenPolicy or policy.required_method != "typed":
            raise PortRefusal("typed_policy_required")
        source = UntrustedText("s9-complete-assembly", assembly.source_generation, assembly.text)
        prepared = prepare_text(source, policy)
        if not isinstance(prepared, PreparedText):
            raise PortRefusal("screen_input_unavailable")
        return bind_native_request(prepared, model=model, captured_wrapped=captured_wrapped)

    def __init__(self, request: ScreenRequestBinding, *, provider: Provider, policy: ScreenPolicy):
        if (
            type(request) is not ScreenRequestBinding
            or type(provider) is not Provider
            or provider.mode not in {"mock", "strict_replay"}
            or type(policy) is not ScreenPolicy
            or policy.required_method != "typed"
            or request.policy_sha256 != policy.sha256
        ):
            raise PortRefusal("native_screen_binding_required")
        self.request, self.provider, self.policy = request, provider, policy

    def check(self, assembly: Assembly, *, binding: CallBinding) -> ScreenVerdict:
        source = UntrustedText("s9-complete-assembly", assembly.source_generation, assembly.text)
        prepared = prepare_text(source, self.policy)
        if not isinstance(prepared, PreparedText):
            raise PortRefusal("screen_input_unavailable")
        result = screen_typed(
            prepared,
            model=self.request.model,
            typed_gateway=self.provider,
            ledger=binding.ledger,
            budget=binding.budget,
            purpose=binding.purpose,
            context=binding.context,
            limits=binding.limits,
            allocation=binding.allocation,
            policy=self.policy,
            request_binding=self.request,
            captured_wrapped=self.request.wrapped if self.request.captured else None,
        )
        if result.decision != "pass" or not native_binding_permits_model_input(
            self.request, result, source, self.policy
        ):
            raise PortRefusal("native_screen_hold")
        return ScreenVerdict(
            input_sha256=result.input_sha256,
            normalized_sha256=result.normalized_sha256,
            source_generation=result.source_generation,
            policy_sha256=result.policy_sha256,
            transform_version=result.transform_version,
            method=result.method,
            coverage=result.coverage,
            normalized_bytes=prepared.normalized_byte_length,
            decision=result.decision,
            deterministic_flags=result.deterministic_flags,
            diagnostic_notices=result.diagnostic_notices,
            adapter_status="ok",
            accounting_ref=result.accounting_ref,
        )
