"""Trusted local host binds actual plan execution to retained source and review gates."""

from dataclasses import dataclass
from pathlib import Path

from ..pipeline.ports import Candidate
from ..runtime.mock import compile_plan
from ..runtime.proofs import ProofStore
from ..shared.grounded.audit import GateError
from ..shared.grounded.models import ItemVersion
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
