"""Project a complete S6 rules result without upgrading its method or authority."""

from ..pipeline.ports import Assembly, CallBinding, PortRefusal, ScreenVerdict
from ..shared.screen import PreparedText, ScreenPolicy, UntrustedText, prepare_text, screen_rules


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
