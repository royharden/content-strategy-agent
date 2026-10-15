import pytest

from content_strategy.shared.grounded.audit import GateError


def test_public_reads_preserve_exact_version_and_do_not_authorize_draft(harness):
    h = harness()
    h.activate()
    content = h.content()
    h.save(content)
    sequence = h.store.sequence
    assert h.store.read_content("rec", 1, actor_label="user") == content
    assert h.store.sequence == sequence
    with pytest.raises(GateError, match="current_approval_required"):
        h.store.require_approved("rec", 1, actor_label="user")
    h.approve(content)
    assert h.store.require_approved("rec", 1, actor_label="user") == content
    h.allowed = False
    for method in (h.store.read_content, h.store.require_approved):
        with pytest.raises(GateError, match="not_authorized"):
            method("rec", 1, actor_label="user")


def test_historical_read_after_edit_is_not_current_approval(harness):
    h = harness()
    h.activate()
    original = h.content()
    h.save(original)
    h.approve(original)
    changed = h.content(revision=2, text="Changed {{cite:fact}}")
    h.save(changed)
    assert h.store.read_content("rec", 1, actor_label="user") == original
    with pytest.raises(GateError, match="stale_item_revision"):
        h.store.require_approved("rec", 1, actor_label="user")
    h.approve(changed)
    assert h.store.require_approved("rec", 2, actor_label="user") == changed


def test_current_screen_hold_blocks_approved_read_without_deleting_history(harness):
    h = harness()
    h.activate()
    original = h.content()
    h.save(original)
    h.approve(original)
    h.screen = "hold"
    with pytest.raises(GateError, match="screen_not_passed"):
        h.store.require_approved("rec", 1, actor_label="user")
    assert h.store.read_content("rec", 1, actor_label="user") == original
