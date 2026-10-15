"""Authored test-only ports. They neither implement S3/S6 nor access providers."""

from datetime import date
from types import SimpleNamespace

import pytest

from content_strategy.ingest import Dataset, PostRow
from content_strategy.metrics import compute_metrics
from content_strategy.pipeline import Pipeline
from content_strategy.pipeline.ports import (
    Bindings,
    CallBinding,
    Candidate,
    GenerationResult,
    ScreenVerdict,
    SupportDecision,
    SupportResult,
    WorkflowPolicy,
)
from content_strategy.shared.grounded import MetricCitation
from content_strategy.shared.grounded.validation import Policy


class Harness:
    def __init__(self):
        self.dataset = Dataset(
            tuple(
                PostRow(
                    f"{scope}{i}", date(2026, 10, 14), scope, "PRIVATE_POST_SENTINEL", 10, 2, 0, 0
                )
                for scope in ("x", "linkedin")
                for i in range(5)
            ),
            "0" * 64,
        )
        self.snapshot = compute_metrics(self.dataset).snapshot
        self.policy = WorkflowPolicy(
            screen_policy_sha256="a" * 64, required_method="rules", origin="mock"
        )
        self.screen_calls, self.generate_calls, self.support_calls = [], [], []
        self.screen_overrides, self.semantic = {}, "supports"
        self.hold_support = False
        self.batches = None
        self.support_override = None
        self.port = Pipeline(
            screen=self,
            generator=self,
            support=self,
            policy=self.policy,
            grounded_policy=Policy(screen_edition="a" * 64),
        )

    def candidate(self, word="alpha", *, scope="x", text=None):
        return Candidate(
            scope=scope,
            text=text or word + " {{cite:er." + scope + ".topic.untagged}}",
            citations=(
                MetricCitation(
                    snapshot_id=self.snapshot.snapshot_id,
                    metric_id=f"er.{scope}.topic.untagged",
                    scope=scope,
                    quoted_value="0.2",
                    unit="ratio",
                ),
            ),
        )

    def bindings(self, *, generation=None, tag_count=0):
        stages = [
            prefix + phase
            for phase in ("initial", "repair")
            for prefix in ("screen.plan.", "plan.", "screen.support.", "support.")
        ]
        stages += [prefix + str(i) for i in range(tag_count) for prefix in ("screen.tag.", "tag.")]
        stages += [
            prefix + phase
            for phase in ("initial", "repair")
            for prefix in ("screen.draft.", "draft.", "screen.support.draft.", "support.draft.")
        ]
        ledger, budget, allocation = object(), object(), object()
        return Bindings(
            {
                stage: CallBinding(
                    "s9." + stage,
                    ledger,
                    budget,
                    SimpleNamespace(
                        purpose="s9." + stage,
                        source_generation=generation or self.snapshot.snapshot_id,
                        policy_sha256=self.policy.screen_policy_sha256,
                        consumer_context_sha256=self.policy.digest,
                    ),
                    SimpleNamespace(max_attempts_total=2, max_content_repairs=0),
                    allocation,
                )
                for stage in stages
            }
        )

    def check(self, assembly, *, binding):
        self.screen_calls.append((assembly, binding))
        fields = {
            "input_sha256": assembly.digest,
            "normalized_sha256": assembly.digest,
            "source_generation": assembly.source_generation,
            "policy_sha256": self.policy.screen_policy_sha256,
            "transform_version": "fixture.identity",
            "method": "rules",
            "coverage": "complete",
            "normalized_bytes": len(assembly.text.encode()),
            "decision": "pass",
            "adapter_status": "ok",
        }
        if self.hold_support and "support" in binding.purpose:
            fields["deterministic_flags"] = ("bot_instruction",)
        return ScreenVerdict(**(fields | self.screen_overrides))

    def generate(self, assembly, *, binding):
        self.generate_calls.append((assembly, binding))
        candidates = (
            self.batches[len(self.generate_calls) - 1]
            if self.batches is not None
            else tuple(
                self.candidate(word) for word in ("alpha", "bravo", "charlie", "delta", "echo")
            )
        )
        if isinstance(candidates, GenerationResult):
            return candidates
        return GenerationResult(
            status="ok", candidates=candidates, origin="mock", model_reported="authored-fixture"
        )

    def judge(self, items, assembly, *, binding):
        self.support_calls.append((items, assembly, binding))
        if self.support_override:
            return self.support_override(items)
        return SupportResult(
            status="ok",
            decisions=tuple(
                SupportDecision(item_id=item.content.item.item_id, verdict=self.semantic)
                for item in items
            ),
            method="jev",
            origin="mock",
        )


@pytest.fixture
def harness():
    return Harness()
