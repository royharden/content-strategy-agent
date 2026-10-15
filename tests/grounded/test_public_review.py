from dataclasses import asdict

import pytest

from content_strategy.shared.grounded.audit import GateError
from content_strategy.shared.grounded.validation import Policy


def test_context_gate_observes_current_policy_and_sequence_without_event_or_lease(harness):
    h = harness()
    with pytest.raises(GateError, match="context_not_initialized"):
        h.store.require_context(h.resolver.generation, actor_label="user")
    h.activate()
    sequence = h.store.sequence
    assert (
        h.store.require_context(
            h.resolver.generation, actor_label="user", expected_sequence=sequence
        )
        == sequence
    )
    assert h.store.sequence == sequence
    h.save(h.content())
    with pytest.raises(GateError, match="sequence_conflict"):
        h.store.require_context(
            h.resolver.generation, actor_label="user", expected_sequence=sequence
        )
    h.allowed = False
    with pytest.raises(GateError, match="not_authorized"):
        h.store.require_context(h.resolver.generation, actor_label="user")
    h.allowed = True
    with pytest.raises(GateError, match="stale_evidence_or_policy"):
        h.store.require_context("b" * 64, actor_label="user")
    h.store.policy = Policy(screen_edition="changed")
    with pytest.raises(GateError, match="stale_evidence_or_policy"):
        h.store.require_context(h.resolver.generation, actor_label="user")


def test_history_requires_empty_and_per_item_permission_and_contains_no_body(harness):
    h = harness()
    h.allowed = False
    with pytest.raises(GateError, match="not_authorized"):
        h.store.history(actor_label="user")
    h.allowed = True
    assert h.store.history(actor_label="user") == ()
    h.journey(text="PRIVATE_BODY {{cite:fact}}")
    rows = h.store.history(actor_label="user")
    assert len(rows) == 2 and all(row.state == "approved" for row in rows)
    assert "PRIVATE_BODY" not in str(rows)
    assert all(
        set(asdict(row)) == {"version", "kind", "parent_id", "parent_revision", "state"}
        for row in rows
    )
    visited = []

    def selective(actor, action, content):
        visited.append(content.item.item_id if content else None)
        return content is None or content.item.item_id == "draft"

    h.store.authorize = selective
    with pytest.raises(GateError, match="not_authorized"):
        h.store.history(actor_label="user")
    assert visited == [None, "draft", "rec"]  # No partially returned list.


def test_fresh_unapproved_draft_review_returns_checked_body_but_grants_no_export(harness):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    h.approve(rec)
    draft = h.content(kind="draft", item_id="draft", parent_id="rec", parent_revision=1)
    h.save(draft)
    sequence = h.store.sequence
    checked, assessment = h.store.review("draft", 1, actor_label="user")
    assert checked.rendered == "Observed 0.125 ratio"
    assert assessment.content_hash == draft.item.content_hash and h.store.sequence == sequence
    assert h.store.state("draft", 1) == "draft"
    with pytest.raises(GateError, match="current_approval_required"):
        h.store.export(h.request(draft))
    h.save(h.content(revision=2))
    with pytest.raises(GateError, match="stale_item_revision"):
        h.store.review("draft", 1, actor_label="user")


@pytest.mark.parametrize(
    "change,code",
    [
        ("hold", "screen_not_passed"),
        ("unknown", "semantic_not_supported"),
        ("stale_assessment", "stale_assessment"),
        ("denied", "not_authorized"),
        ("context", "stale_evidence_or_policy"),
    ],
)
def test_review_refuses_before_body_return_and_preserves_state(harness, change, code):
    h = harness()
    rec, _ = h.journey()
    if change == "hold":
        h.screen = "hold"
    elif change == "unknown":
        h.semantic = "unknown"
    elif change == "stale_assessment":
        h.assessment_overrides["content_hash"] = "b" * 64
    elif change == "denied":
        h.allowed = False
    else:
        h.store.activate_context("b" * 64, expected_sequence=h.store.sequence)
    sequence = h.store.sequence
    with pytest.raises(GateError, match=code):
        h.store.review(rec.item.item_id, 1, actor_label="user")
    assert h.store.sequence == sequence
