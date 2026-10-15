"""Pre-refactor input-byte compatibility fixtures; not independent quality evaluation."""

import hashlib
import json
from pathlib import Path

import pytest

from content_strategy.metrics.grounding import MetricsResolver
from content_strategy.pipeline.drafting import draft
from content_strategy.pipeline.ports import WorkflowPolicy
from content_strategy.shared.grounded.audit import AuditStore
from content_strategy.shared.grounded.validation import Assessment, seal_content

SCENARIOS = ("plan", "plan-repair", "plan-capped", "draft", "draft-repair")


def capture(h, scenario, tmp_path):
    records = []

    def record(kind, assembly, binding):
        records.append(
            {
                "port": kind,
                "purpose": binding.purpose,
                "generation": assembly.source_generation,
                "text": assembly.text,
                "sha256": hashlib.sha256(assembly.text.encode("utf-8")).hexdigest(),
            }
        )

    original_screen, original_generate, original_judge = h.check, h.generate, h.judge

    def check(assembly, *, binding):
        record("screen", assembly, binding)
        return original_screen(assembly, binding=binding)

    def generate(assembly, *, binding):
        record("generation", assembly, binding)
        return original_generate(assembly, binding=binding)

    def judge(items, assembly, *, binding):
        record("support", assembly, binding)
        return original_judge(items, assembly, binding=binding)

    h.check, h.generate, h.judge = check, generate, judge
    if scenario == "plan-repair":
        h.batches = [
            tuple(h.candidate(word) for word in ("alpha", "bravo", "charlie", "delta"))
            + (h.candidate("bad", text="Unsupported 10% {{cite:er.x.topic.untagged}}"),),
            (h.candidate("echo"),),
        ]
    if scenario == "plan-capped":
        h.policy = WorkflowPolicy.model_validate(h.policy.model_dump() | {"max_metric_rows": 3})
        h.port.policy = h.policy
    if scenario.startswith("plan"):
        result = h.port.plan(h.snapshot, "Suggest useful material", bindings=h.bindings())
        accepted = result.accepted
        repaired = result.repaired_proposals
    else:
        candidate = h.candidate("approved alpha", scope="linkedin")
        parent = seal_content(
            item_id="rec",
            revision=1,
            kind="recommendation",
            scope="linkedin",
            snapshot_id=h.snapshot.snapshot_id,
            text=candidate.text,
            citations=candidate.citations,
        )

        def assess(checked, policy):
            return Assessment(
                content_hash=checked.content.item.content_hash,
                evidence_hash=checked.evidence_hash,
                policy_hash=policy.digest,
                screen_edition=policy.screen_edition,
                screen_status="pass",
                semantic_status="supports",
            )

        store = AuditStore(
            tmp_path / "parity.sqlite3",
            namespace="parity",
            policy=h.port.grounded_policy,
            resolver=MetricsResolver(h.snapshot),
            authorize=lambda actor, action, content: actor == "user",
            assess=assess,
        )
        try:
            store.activate_context(h.snapshot.snapshot_id, expected_sequence=0)
            store.save(
                parent, actor_label="user", expected_revision=0, expected_sequence=store.sequence
            )
            store.decide(
                "rec", 1, approve=True, actor_label="user", expected_sequence=store.sequence
            )
            h.batches = [(h.candidate("draft alpha", scope="linkedin"),)]
            if scenario == "draft-repair":
                h.batches = [
                    (
                        h.candidate(
                            "long",
                            scope="linkedin",
                            text="body " * 700 + "{{cite:er.linkedin.topic.untagged}}",
                        ),
                    ),
                    (h.candidate("draft beta", scope="linkedin"),),
                ]
            result = draft(
                h.port,
                parent,
                h.snapshot,
                "Suggest useful material",
                authority=store,
                actor_label="user",
                bindings=h.bindings(),
            )
            accepted = (result.accepted,) if result.accepted else ()
            repaired = None
        finally:
            store.close()
    assert all("PRIVATE_POST_SENTINEL" not in row["text"] for row in records)
    return {
        "calls": records,
        "outcome": {
            "proposed": result.proposed,
            "repaired_proposals": repaired,
            "accepted_hashes": [v.checked.content.item.content_hash for v in accepted],
            "drops": [{"item_id": v.item_id, "codes": list(v.codes)} for v in result.dropped],
        },
    }


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_exact_pre_refactor_assemblies_and_outcomes(harness, scenario, tmp_path):
    frozen = json.loads((Path(__file__).parent / "fixtures/assembly-v1.json").read_bytes())
    assert capture(harness, scenario, tmp_path) == frozen["scenarios"][scenario]
