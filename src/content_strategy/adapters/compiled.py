"""Dispatch only previously prepared exact offline requests; no late registration."""

from dataclasses import dataclass
from types import MappingProxyType

from ..pipeline.ports import (
    Assembly,
    CallBinding,
    GenerationResult,
    PortRefusal,
    SupportDecision,
    SupportResult,
)
from ..shared.grounded.identity import canonical_json
from ..shared.providers.models import GenerateRequest, TypedJudgmentRequest
from .provider import OfflineGateway


@dataclass(frozen=True)
class CompiledCall:
    assembly: Assembly
    request: GenerateRequest | TypedJudgmentRequest
    binding: CallBinding
    gateway: OfflineGateway
    item_hashes: tuple[tuple[str, str], ...] = ()

    def run(self, assembly, binding):
        if assembly != self.assembly or binding.purpose != self.binding.purpose:
            raise PortRefusal("uncompiled_input")
        if any(
            getattr(binding, key) is not getattr(self.binding, key)
            for key in ("ledger", "budget", "context", "limits", "allocation")
        ):
            raise PortRefusal("compiled_binding_changed")
        if assembly.source_generation != binding.context.source_generation:
            raise PortRefusal("compiled_generation_changed")
        result = self.gateway.run(self.request, binding=binding).validate_for(self.request)
        if result.status != "ok" or result.source_capture is None:
            raise PortRefusal("compiled_source_unavailable")
        return result


class CompiledPorts:
    """One-shot original requests. Unknown repair stages fail before fixture lookup."""

    def __init__(self, calls, screens):
        self.calls = MappingProxyType(dict(calls))
        self.screens = MappingProxyType(dict(screens))
        self.completed = set()
        self.results = []
        self.screen_results = {}

    def check(self, assembly, *, binding):
        pair = self.screens.get(binding.purpose)
        if pair is None:
            raise PortRefusal("uncompiled_screen")
        call, native = pair
        if (
            assembly != call.assembly
            or any(
                getattr(binding, key) is not getattr(call.binding, key)
                for key in ("ledger", "budget", "context", "limits", "allocation")
            )
            or binding.purpose != call.binding.purpose
        ):
            raise PortRefusal("uncompiled_screen_input")
        result = native.check(assembly, binding=binding)
        self.completed.add(binding.context.child_id)
        self.screen_results[binding.purpose] = result
        return result

    def _call(self, assembly, binding):
        call = self.calls.get(binding.purpose)
        if call is None:
            raise PortRefusal("uncompiled_stage")
        result = call.run(assembly, binding)
        self.completed.add(binding.context.child_id)
        self.results.append(result)
        return call, result

    def generate(self, assembly, *, binding):
        call, result = self._call(assembly, binding)
        if type(call.request) is not GenerateRequest or result.kind != "generated":
            raise PortRefusal("compiled_generation_kind")
        if not isinstance(result.parsed, dict) or set(result.parsed) != {"candidates"}:
            raise PortRefusal("compiled_generation_shape")
        return GenerationResult.model_validate_json(
            canonical_json(
                {
                    "status": "ok",
                    "candidates": result.parsed["candidates"],
                    "origin": result.origin,
                    "model_reported": result.model_reported,
                    "accounting_ref": result.accounting_ref,
                }
            )
        )

    def judge(self, items, assembly, *, binding):
        call = self.calls.get(binding.purpose)
        hashes = tuple(
            (item.content.item.item_id, item.content.item.content_hash) for item in items
        )
        if call is None or hashes != call.item_hashes:
            raise PortRefusal("uncompiled_support_items")
        _, result = self._call(assembly, binding)
        if type(call.request) is not TypedJudgmentRequest or result.kind != "typed":
            raise PortRefusal("compiled_support_kind")
        result.typed.validate_for(call.request)
        return SupportResult(
            status="ok",
            decisions=tuple(
                SupportDecision(item_id=key, verdict=result.typed.answers[key].choice)
                for key, _ in hashes
            ),
            method="jev",
            origin=result.origin,
            accounting_ref=result.accounting_ref,
        )
