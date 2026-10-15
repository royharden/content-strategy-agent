"""Single-draft orchestration; authority is host-injected and rechecked, never a user flag."""

from dataclasses import dataclass
from typing import Protocol

from ..metrics.grounding import MetricsResolver
from ..platforms import check_target
from ..shared.grounded.identity import identity_hash
from ..shared.grounded.models import MetricSnapshot
from ..shared.grounded.validation import Content, seal_content, validate
from . import Drop, Evaluated, Pipeline
from .assembly import draft_document, draft_repair_document, draft_support_document
from .ports import Assembly, Bindings, PortRefusal, SupportResult


class ParentAuthority(Protocol):
    def require_approved(self, item_id: str, revision: int, *, actor_label: str) -> Content: ...


@dataclass(frozen=True)
class DraftResult:
    accepted: Evaluated | None
    dropped: tuple[Drop, ...]
    proposed: int


def _parent_current(authority, parent, actor_label):
    try:
        current = Content.model_validate(
            authority.require_approved(
                parent.item.item_id, parent.item.revision, actor_label=actor_label
            ).model_dump(mode="python")
        )
    except Exception:
        raise PortRefusal("parent_approval_required") from None
    if current != parent or current.item.kind != "recommendation":
        raise PortRefusal("parent_version_mismatch")


def draft(
    pipeline: Pipeline,
    parent: Content,
    snapshot: MetricSnapshot,
    brief: str,
    *,
    authority: ParentAuthority,
    actor_label: str,
    bindings: Bindings,
) -> DraftResult:
    parent = Content.model_validate(parent.model_dump(mode="python"))
    snapshot = MetricSnapshot.model_validate(snapshot.model_dump(mode="python"))
    if not isinstance(brief, str) or len(brief) > 4000:
        raise PortRefusal("brief_limit")
    _parent_current(authority, parent, actor_label)
    if parent.item.snapshot_id != snapshot.snapshot_id:
        raise PortRefusal("parent_snapshot_mismatch")
    if not check_target(parent.item.scope, "").supported:
        raise PortRefusal("target_capability_unavailable")
    resolver = MetricsResolver(snapshot)
    parent_checked = validate(parent, resolver, pipeline.grounded_policy)
    if parent_checked.report.structural_status != "valid":
        raise PortRefusal("invalid_parent_grounding")
    generation = snapshot.snapshot_id
    bindings.require(
        [
            prefix + phase
            for phase in ("initial", "repair")
            for prefix in ("screen.draft.", "draft.", "screen.support.draft.", "support.draft.")
        ],
        generation,
        pipeline.policy,
    )
    document = draft_document(parent_checked, snapshot, brief)
    proposed, drops = 0, []
    for phase in ("initial", "repair"):
        _parent_current(authority, parent, actor_label)
        if drops:
            document = draft_repair_document(document, (value.codes for value in drops))
        try:
            result = pipeline._generate(
                Assembly.build(document, generation), "draft." + phase, bindings
            )
            _parent_current(authority, parent, actor_label)
        except PortRefusal as error:
            drops.append(Drop("draft." + phase, (str(error),)))
            break
        proposed += len(result.candidates)
        if len(result.candidates) != 1:
            drops.append(Drop("draft." + phase, ("single_draft_required",)))
            continue
        candidate = result.candidates[0]
        if candidate.scope != parent.item.scope or {
            c.model_dump_json() for c in candidate.citations
        } != {c.model_dump_json() for c in parent.item.citations}:
            drops.append(Drop("draft." + phase, ("parent_evidence_mismatch",)))
            continue
        try:
            item_id = (
                "draft-"
                + identity_hash(
                    {
                        "parent": parent.item.content_hash,
                        "candidate": candidate.model_dump(mode="python"),
                    }
                )[:24]
            )
            content = seal_content(
                item_id=item_id,
                revision=1,
                kind="draft",
                scope=candidate.scope,
                snapshot_id=generation,
                text=candidate.text,
                citations=candidate.citations,
                editorial=candidate.editorial,
                parent_id=parent.item.item_id,
                parent_revision=parent.item.revision,
            )
            checked = validate(content, resolver, pipeline.grounded_policy)
        except ValueError:
            drops.append(Drop("draft." + phase, ("invalid_draft_encoding_or_shape",)))
            continue
        if checked.report.failures:
            drops.append(Drop(item_id, tuple(f.code for f in checked.report.failures)))
            continue
        target = check_target(candidate.scope, checked.rendered)
        if not target.valid:
            drops.append(Drop(item_id, (target.reason,)))
            continue
        assembly = Assembly.build(
            draft_support_document(checked, parent_checked, document), generation
        )
        try:
            screen = pipeline.screened(
                assembly, stage="screen.support.draft." + phase, bindings=bindings
            )
        except PortRefusal as error:
            drops.append(Drop(item_id, (str(error),)))
            break
        try:
            support = SupportResult.model_validate(
                pipeline.support.judge(
                    (checked,),
                    assembly,
                    binding=bindings.get("support.draft." + phase, generation, pipeline.policy),
                ).model_dump()
            )
            if (
                support.status != "ok"
                or len(support.decisions) != 1
                or support.decisions[0].item_id != item_id
                or support.origin != pipeline.policy.origin
                or (support.origin == "live" and support.accounting_ref is None)
            ):
                raise PortRefusal("semantic_coverage")
        except Exception:
            drops.append(Drop(item_id, ("semantic_unavailable",)))
            break
        if support.decisions[0].verdict != "supports":
            drops.append(Drop(item_id, ("semantic_" + support.decisions[0].verdict,)))
            continue
        try:
            _parent_current(authority, parent, actor_label)
        except PortRefusal as error:
            drops.append(Drop(item_id, (str(error),)))
            break
        return DraftResult(
            Evaluated(checked, screen, support.method, support.origin), tuple(drops), proposed
        )
    return DraftResult(None, tuple(drops), proposed)
