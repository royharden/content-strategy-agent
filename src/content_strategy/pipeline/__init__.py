"""Metric-only orchestration through injected staging ports; no default provider/screen."""

from dataclasses import dataclass

from ..metrics.grounding import MetricsResolver
from ..shared.grounded.identity import identity_hash
from ..shared.grounded.models import MetricSnapshot
from ..shared.grounded.validation import Checked, Policy, seal_content, validate
from .assembly import plan_document, plan_repair_document, plan_support_document, select_metrics
from .ports import (
    Assembly,
    Bindings,
    GenerationPort,
    GenerationResult,
    PortRefusal,
    ScreenPort,
    ScreenVerdict,
    SupportPort,
    SupportResult,
    WorkflowPolicy,
)


@dataclass(frozen=True)
class Drop:
    item_id: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class Evaluated:
    checked: Checked
    screen: ScreenVerdict
    support_method: str
    origin: str


@dataclass(frozen=True)
class Strategy:
    accepted: tuple[Evaluated, ...]
    dropped: tuple[Drop, ...]
    proposed: int
    repaired_proposals: int
    citable_total: int
    selected_metrics: int

    @property
    def underfilled(self):
        return len(self.accepted) < 5


class Pipeline:
    def __init__(
        self,
        *,
        screen: ScreenPort,
        generator: GenerationPort,
        support: SupportPort,
        policy: WorkflowPolicy,
        grounded_policy: Policy,
    ):
        self.screen, self.generator, self.support = screen, generator, support
        self.policy, self.grounded_policy = policy, grounded_policy

    def screened(self, assembly, *, stage, bindings):
        if len(assembly.text.encode("utf-8")) > 32768:
            raise PortRefusal("input_too_large")
        binding = bindings.get(stage, assembly.source_generation, self.policy)
        try:
            result = ScreenVerdict.model_validate(
                self.screen.check(assembly, binding=binding).model_dump()
            )
        except Exception:
            raise PortRefusal("screen_invalid") from None
        if (result.input_sha256, result.source_generation, result.policy_sha256, result.method) != (
            assembly.digest,
            assembly.source_generation,
            self.policy.screen_policy_sha256,
            self.policy.required_method,
        ):
            raise PortRefusal("screen_identity_mismatch")
        if (
            result.decision != "pass"
            or result.coverage != "complete"
            or result.deterministic_flags
            or result.normalized_bytes > 32768
            or result.adapter_status != "ok"
            or (
                result.method == "typed_live"
                and (result.operating_authority_sha256 is None or result.accounting_ref is None)
            )
        ):
            raise PortRefusal("screen_hold")
        return result

    def _generate(self, assembly, stage, bindings):
        self.screened(assembly, stage="screen." + stage, bindings=bindings)
        binding = bindings.get(stage, assembly.source_generation, self.policy)
        try:
            result = GenerationResult.model_validate(
                self.generator.generate(assembly, binding=binding).model_dump()
            )
        except Exception:
            raise PortRefusal("generation_invalid") from None
        if result.status != "ok" or result.model_reported is None:
            raise PortRefusal("generation_" + result.status)
        if not result.candidates:
            raise PortRefusal("generation_empty")
        if result.origin != self.policy.origin:
            raise PortRefusal("generation_origin_mismatch")
        if result.origin == "live" and result.accounting_ref is None:
            raise PortRefusal("generation_accounting_missing")
        return result

    def plan(self, snapshot: MetricSnapshot, brief: str, *, bindings: Bindings) -> Strategy:
        snapshot = MetricSnapshot.model_validate(snapshot.model_dump(mode="python"))
        if not isinstance(brief, str) or len(brief) > 4000:
            raise PortRefusal("brief_limit")
        projection = select_metrics(snapshot, self.policy.max_metric_rows)
        citable, selected = projection.citable, projection.selected
        if not selected:
            return Strategy((), (), 0, 0, 0, 0)
        table = projection.table()
        generation = snapshot.snapshot_id
        bindings.require(
            [
                prefix + phase
                for phase in ("initial", "repair")
                for prefix in ("screen.plan.", "plan.", "screen.support.", "support.")
            ],
            generation,
            self.policy,
        )
        document = plan_document(brief, table)
        resolver = MetricsResolver(snapshot)
        selected_keys = {metric.metric_id for metric in selected}
        accepted, dropped = [], []
        proposed, repaired = 0, 0
        seen = set()
        for phase in ("initial", "repair"):
            if phase == "repair":
                if not dropped or len(accepted) >= 10:
                    break
                document = plan_repair_document(document, (value.codes for value in dropped))
            try:
                assembly = Assembly.build(document, generation)
                result = self._generate(assembly, "plan." + phase, bindings)
            except PortRefusal as error:
                dropped.append(Drop("batch." + phase, (str(error),)))
                break
            proposed += len(result.candidates)
            if phase == "repair":
                repaired += len(result.candidates)
            pending = []
            for index, candidate in enumerate(result.candidates):
                try:
                    item_id = "rec-" + identity_hash(candidate.model_dump(mode="python"))[:24]
                except ValueError:
                    dropped.append(Drop("candidate." + str(index), ("invalid_candidate_encoding",)))
                    continue
                if item_id in seen:
                    dropped.append(Drop(item_id, ("duplicate_candidate",)))
                    continue
                seen.add(item_id)
                if candidate.scope == "multi" or any(
                    c.metric_id not in selected_keys for c in candidate.citations
                ):
                    dropped.append(Drop(item_id, ("outside_metric_projection",)))
                    continue
                content = seal_content(
                    item_id=item_id,
                    revision=1,
                    kind="recommendation",
                    scope=candidate.scope,
                    snapshot_id=generation,
                    text=candidate.text,
                    citations=candidate.citations,
                    editorial=candidate.editorial,
                )
                checked = validate(content, resolver, self.grounded_policy)
                if checked.report.failures:
                    dropped.append(Drop(item_id, tuple(f.code for f in checked.report.failures)))
                else:
                    pending.append(checked)
            if not pending:
                continue
            support_assembly = Assembly.build(plan_support_document(pending, table), generation)
            try:
                screen = self.screened(
                    support_assembly, stage="screen.support." + phase, bindings=bindings
                )
            except PortRefusal as error:
                dropped.extend(Drop(value.content.item.item_id, (str(error),)) for value in pending)
                break
            try:
                binding = bindings.get("support." + phase, generation, self.policy)
                support = SupportResult.model_validate(
                    self.support.judge(
                        tuple(pending), support_assembly, binding=binding
                    ).model_dump()
                )
                ids = [decision.item_id for decision in support.decisions]
                if (
                    support.status != "ok"
                    or set(ids) != {value.content.item.item_id for value in pending}
                    or len(ids) != len(set(ids))
                ):
                    raise PortRefusal("semantic_coverage")
                if support.origin != self.policy.origin:
                    raise PortRefusal("semantic_origin_mismatch")
                if support.origin == "live" and support.accounting_ref is None:
                    raise PortRefusal("semantic_accounting_missing")
            except Exception:
                dropped.extend(
                    Drop(value.content.item.item_id, ("semantic_unavailable_or_held",))
                    for value in pending
                )
                break
            decisions = {decision.item_id: decision.verdict for decision in support.decisions}
            for checked in pending:
                item_id = checked.content.item.item_id
                if decisions[item_id] != "supports":
                    dropped.append(Drop(item_id, ("semantic_" + decisions[item_id],)))
                elif len(accepted) == 10:
                    dropped.append(Drop(item_id, ("response_capacity",)))
                else:
                    accepted.append(Evaluated(checked, screen, support.method, support.origin))
        return Strategy(
            tuple(accepted), tuple(dropped), proposed, repaired, len(citable), len(selected)
        )
