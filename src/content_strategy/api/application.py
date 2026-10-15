"""Trusted local host binds actual plan execution to retained source and review gates."""

from dataclasses import dataclass
from pathlib import Path

from ..pipeline.ports import Candidate
from ..runtime.mock import compile_draft, compile_edit, compile_plan
from ..runtime.proofs import ProofStore
from ..shared.grounded.audit import GateError
from ..shared.grounded.models import ItemVersion
from ..shared.grounded.validation import seal_content
from ..shared.screen import ScreenPolicy
from .service import LocalReviewService, Selection


@dataclass(frozen=True)
class Planned:
    versions: tuple[ItemVersion, ...]
    sequence: int
    underfilled: bool
    proposed: int
    dropped_codes: tuple[tuple[str, ...], ...]
    execution_origin: str = "authored_synthetic_mock"


@dataclass(frozen=True)
class Drafted:
    version: ItemVersion | None
    sequence: int
    proposed: int
    dropped_codes: tuple[tuple[str, ...], ...]
    execution_origin: str = "authored_synthetic_mock"


class PlanningHost:
    """No web body may provide candidates, judgments or proofs to this trusted seam.

    A higher-level host selects explicit authored mock inputs or a separately
    authorized real execution implementation. These records never become approvals.
    """

    def __init__(
        self,
        review: LocalReviewService,
        proofs: ProofStore,
        *,
        call_database: Path,
        screen_policy: ScreenPolicy,
    ):
        if (
            type(review) is not LocalReviewService
            or type(proofs) is not ProofStore
            or review.database != proofs.database
            or review.namespace != proofs.namespace
            or review.assess != proofs.assess
            or review.policy.screen_edition != screen_policy.sha256
            or Path(call_database).resolve() == review.database.resolve()
        ):
            raise GateError("trusted_host_binding_required")
        self.review, self.proofs = review, proofs
        self.call_database, self.screen_policy = Path(call_database), screen_policy

    def run_authored_plan(
        self,
        selection: Selection,
        brief: str,
        candidates: tuple[Candidate, ...],
        *,
        screen_scores: dict,
        support_verdicts: dict,
        expected_sequence: int,
    ) -> Planned:
        review = self.review
        review._allow("plan")
        review.require_context(selection, expected_sequence=expected_sequence)
        retained = review.report(selection)
        runtime = compile_plan(
            self.call_database,
            retained.report.snapshot,
            brief,
            candidates,
            namespace=review.namespace,
            screen_policy=self.screen_policy,
            screen_scores=screen_scores,
            support_verdicts=support_verdicts,
        )
        try:
            if runtime.pipeline.grounded_policy.digest != review.policy.digest:
                raise GateError("host_policy_mismatch")
            strategy = runtime.run()
            # The earlier check is no lease. Reject changed source, policy or CAS
            # before retaining any proof or attempting the first content write.
            sequence = review.require_context(selection, expected_sequence=expected_sequence)
            if strategy.accepted:
                self.proofs.retain(runtime)
            versions = []
            for accepted in strategy.accepted:
                content = accepted.checked.content
                sequence = review.save(
                    selection, content, expected_revision=0, expected_sequence=sequence
                )
                item = content.item
                versions.append(
                    ItemVersion(
                        item_id=item.item_id,
                        revision=item.revision,
                        content_hash=item.content_hash,
                        evidence_generation=item.snapshot_id,
                    )
                )
            review.require_context(selection, expected_sequence=sequence)
            # Return metadata only. Bodies require the independent preview gate.
            return Planned(
                tuple(versions),
                sequence,
                strategy.underfilled,
                strategy.proposed,
                tuple(drop.codes for drop in strategy.dropped),
            )
        finally:
            runtime.close()

    def run_authored_draft(
        self,
        selection: Selection,
        parent_version: ItemVersion,
        brief: str,
        candidate: Candidate,
        *,
        screen_scores: dict,
        support_verdict: str,
        expected_sequence: int,
    ) -> Drafted:
        review = self.review
        review._allow("draft")
        review.require_context(selection, expected_sequence=expected_sequence)
        retained = review.report(selection)
        parent = review.read(selection, parent_version)
        # Keep the real approval authority alive through all original before/after
        # generation checks. It never opens an approval event automatically.
        with review._audit(selection) as authority:
            runtime = compile_draft(
                self.call_database,
                retained.report.snapshot,
                brief,
                parent,
                candidate,
                namespace=review.namespace,
                screen_policy=self.screen_policy,
                screen_scores=screen_scores,
                support_verdict=support_verdict,
                authority=authority,
                actor_label=review.actor_label,
            )
            try:
                if runtime.pipeline.grounded_policy.digest != review.policy.digest:
                    raise GateError("host_policy_mismatch")
                result = runtime.run()
                sequence = review.require_context(selection, expected_sequence=expected_sequence)
                version = None
                if result.accepted is not None:
                    self.proofs.retain(runtime)
                    content = result.accepted.checked.content
                    sequence = review.save(
                        selection, content, expected_revision=0, expected_sequence=sequence
                    )
                    item = content.item
                    version = ItemVersion(
                        item_id=item.item_id,
                        revision=item.revision,
                        content_hash=item.content_hash,
                        evidence_generation=item.snapshot_id,
                    )
                review.require_context(selection, expected_sequence=sequence)
                return Drafted(
                    version, sequence, result.proposed, tuple(drop.codes for drop in result.dropped)
                )
            finally:
                runtime.close()

    def run_authored_edit(
        self,
        selection: Selection,
        version: ItemVersion,
        text: str,
        *,
        screen_scores: dict,
        support_verdict: str,
        expected_sequence: int,
    ) -> Drafted:
        review = self.review
        review._allow("edit")
        review.require_context(selection, expected_sequence=expected_sequence)
        retained = review.report(selection)
        with review._audit(selection) as authority:
            checked, _ = authority.review(
                version.item_id, version.revision, actor_label=review.actor_label
            )
            original = checked.content
            if (
                original.item.content_hash != version.content_hash
                or original.item.snapshot_id != version.evidence_generation
            ):
                raise GateError("version_mismatch")
            fields = original.item.model_dump(mode="python", exclude={"content_hash"})
            fields.update(text=text, revision=version.revision + 1)
            content = seal_content(
                **fields, editorial=original.editorial, passages=original.passages
            )
            parent = None
            if original.item.kind == "draft":
                parent = authority.require_approved(
                    original.item.parent_id,
                    original.item.parent_revision,
                    actor_label=review.actor_label,
                )
            runtime = compile_edit(
                self.call_database,
                retained.report.snapshot,
                content,
                namespace=review.namespace,
                screen_policy=self.screen_policy,
                screen_scores=screen_scores,
                support_verdict=support_verdict,
                parent=parent,
                authority=authority,
                actor_label=review.actor_label,
            )
            try:
                if runtime.pipeline.grounded_policy.digest != review.policy.digest:
                    raise GateError("host_policy_mismatch")
                result = runtime.run()
                sequence = review.require_context(selection, expected_sequence=expected_sequence)
                edited = None
                if result.accepted is not None:
                    self.proofs.retain(runtime)
                    sequence = review.save(
                        selection,
                        content,
                        expected_revision=version.revision,
                        expected_sequence=sequence,
                    )
                    edited = ItemVersion(
                        item_id=content.item.item_id,
                        revision=content.item.revision,
                        content_hash=content.item.content_hash,
                        evidence_generation=content.item.snapshot_id,
                    )
                review.require_context(selection, expected_sequence=sequence)
                return Drafted(
                    edited,
                    sequence,
                    result.proposed,
                    tuple(drop.codes for drop in result.dropped),
                    execution_origin="human_edit_with_authored_synthetic_assessment",
                )
            finally:
                runtime.close()
