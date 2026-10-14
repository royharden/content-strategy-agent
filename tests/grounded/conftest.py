"""Synthetic injected authority/reviews are explicit test fixtures, never production defaults."""

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from content_strategy.shared.grounded import Metric, MetricCitation
from content_strategy.shared.grounded.audit import AuditStore, ExportRequest
from content_strategy.shared.grounded.validation import Assessment, Policy, seal_content

GEN = "a" * 64


@dataclass
class Resolver:
    generation: str = GEN
    metrics: dict = field(default_factory=dict)

    def current_generation(self, scope):
        return self.generation if scope == "corpus" else None

    def resolve(self, key):
        return (
            self.metrics.get(key.evidence_id)
            if key.generation == self.current_generation(key.scope)
            else None
        )


class Harness:
    def __init__(self, path, *, namespace="test", policy=None, **options):
        self.resolver = Resolver()
        self.metric = Metric(
            metric_id="fact",
            snapshot_id=GEN,
            scope="corpus",
            definition="Exact synthetic evidence",
            value=Decimal("0.125"),
            unit="ratio",
            sample_size=5,
            computed_by="oracle.v1",
            status="ok",
        )
        self.resolver.metrics["fact"] = self.metric
        self.policy = policy or Policy(screen_edition="injected-fixture.v1")
        self.screen, self.semantic = "pass", "supports"
        self.assessment_overrides = {}
        self.allowed = True
        self.store = AuditStore(
            path,
            namespace=namespace,
            policy=self.policy,
            resolver=self.resolver,
            authorize=lambda actor, action, content: self.allowed and actor == "user",
            assess=self.assess,
            **options,
        )

    def assess(self, checked, policy):
        return Assessment(
            **(
                {
                    "content_hash": checked.content.item.content_hash,
                    "evidence_hash": checked.evidence_hash,
                    "policy_hash": policy.digest,
                    "screen_edition": policy.screen_edition,
                    "screen_status": self.screen,
                    "semantic_status": self.semantic,
                }
                | self.assessment_overrides
            )
        )

    def content(
        self,
        *,
        item_id="rec",
        revision=1,
        kind="recommendation",
        text="Observed {{cite:fact}}",
        citations=None,
        editorial=(),
        **changes,
    ):
        fields = {
            "item_id": item_id,
            "revision": revision,
            "kind": kind,
            "scope": "corpus",
            "snapshot_id": GEN,
            "text": text,
            "citations": (
                MetricCitation(
                    snapshot_id=GEN,
                    metric_id="fact",
                    scope="corpus",
                    quoted_value="0.125",
                    unit="ratio",
                ),
            )
            if citations is None
            else citations,
        }
        return seal_content(editorial=editorial, **(fields | changes))

    def activate(self):
        self.store.activate_context(GEN, expected_sequence=self.store.sequence)

    def save(self, content):
        self.store.save(
            content,
            actor_label="user",
            expected_revision=content.item.revision - 1,
            expected_sequence=self.store.sequence,
        )

    def approve(self, content):
        return self.store.decide(
            content.item.item_id,
            content.item.revision,
            approve=True,
            actor_label="user",
            expected_sequence=self.store.sequence,
        )

    def journey(self, *, text="Draft {{cite:fact}}", item_id="draft"):
        self.activate()
        rec = self.content()
        self.save(rec)
        self.approve(rec)
        draft = self.content(
            kind="draft", item_id=item_id, parent_id="rec", parent_revision=1, text=text
        )
        self.save(draft)
        self.approve(draft)
        return rec, draft

    def request(self, draft, **changes):
        from content_strategy.shared.grounded.audit import _version

        fields = {
            "idempotency_key": "download",
            "actor_label": "user",
            "generation": GEN,
            "policy_hash": self.policy.digest,
            "expected_sequence": self.store.sequence,
            "items": (_version(draft),),
        }
        return ExportRequest(**(fields | changes))


@pytest.fixture
def harness(tmp_path):
    opened = []

    def create(**options):
        result = Harness(tmp_path / "authority.sqlite3", **options)
        opened.append(result)
        return result

    yield create
    for result in opened:
        result.store.close()
