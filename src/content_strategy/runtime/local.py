"""Explicit local authored-mock host; no live clients or implicit approvals."""

from pathlib import Path

from ..api.application import PlanningHost
from ..api.service import LocalReviewService
from ..shared.grounded.validation import Policy
from ..shared.screen import ScreenPolicy
from ..shared.screen.models import HAZARDS
from .proofs import ProofStore


def local_host(database: Path, call_database: Path, namespace: str) -> PlanningHost:
    proofs = ProofStore(database, namespace=namespace)
    screen = ScreenPolicy(
        "s9-cli-authored-mock.v1",
        "typed",
        profile_id="s9-synthetic-smoke.v1",
        thresholds=dict.fromkeys(HAZARDS, 0.35),
        threshold_provenance="exploratory_seed",
    )
    review = LocalReviewService(
        database,
        namespace=namespace,
        actor_label="local-terminal-user",
        policy=Policy(screen_edition=screen.sha256),
        authorize=lambda actor, action, content: actor == "local-terminal-user",
        assess=proofs.assess,
    )
    return PlanningHost(review, proofs, call_database=call_database, screen_policy=screen)
