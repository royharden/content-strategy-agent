import pytest

from content_strategy.metrics.grounding import MetricsResolver
from content_strategy.pipeline.drafting import draft
from content_strategy.pipeline.ports import PortRefusal
from content_strategy.shared.grounded.audit import AuditStore, ExportRequest
from content_strategy.shared.grounded.models import ItemVersion
from content_strategy.shared.grounded.validation import Assessment, seal_content


@pytest.fixture
def context(harness, tmp_path):
    h = harness

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
        tmp_path / "authority.sqlite3",
        namespace="test",
        policy=h.port.grounded_policy,
        resolver=MetricsResolver(h.snapshot),
        authorize=lambda actor, *args: actor == "user",
        assess=assess,
    )
    store.activate_context(h.snapshot.snapshot_id, expected_sequence=0)
    candidate = h.candidate(scope="linkedin")
    parent = seal_content(
        item_id="rec",
        revision=1,
        kind="recommendation",
        scope="linkedin",
        snapshot_id=h.snapshot.snapshot_id,
        text=candidate.text,
        citations=candidate.citations,
    )
    store.save(parent, actor_label="user", expected_revision=0, expected_sequence=store.sequence)
    h.batches = [(h.candidate("draft alpha", scope="linkedin"),)]
    yield h, store, parent, store
    store.close()


def approve_parent(store):
    store.decide("rec", 1, approve=True, actor_label="user", expected_sequence=store.sequence)


def test_actual_approved_parent_required_before_any_generation(context):
    h, store, parent, authority = context
    with pytest.raises(PortRefusal, match="parent_approval_required"):
        draft(
            h.port,
            parent,
            h.snapshot,
            "Brief",
            authority=authority,
            actor_label="user",
            bindings=h.bindings(),
        )
    assert not h.generate_calls and not h.screen_calls


def test_positive_draft_inherits_and_can_enter_actual_second_approval_export(context):
    h, store, parent, authority = context
    approve_parent(store)
    result = draft(
        h.port,
        parent,
        h.snapshot,
        "Brief",
        authority=authority,
        actor_label="user",
        bindings=h.bindings(),
    )
    assert result.accepted and result.proposed == 1
    content = result.accepted.checked.content
    assert content.item.parent_id == "rec" and content.item.parent_revision == 1
    assert content.item.citations == parent.item.citations
    store.save(content, actor_label="user", expected_revision=0, expected_sequence=store.sequence)
    store.decide(
        content.item.item_id, 1, approve=True, actor_label="user", expected_sequence=store.sequence
    )
    assert store.state(content.item.item_id, 1) == "approved"
    request = ExportRequest(
        idempotency_key="draft-download",
        actor_label="user",
        generation=h.snapshot.snapshot_id,
        policy_hash=h.port.grounded_policy.digest,
        expected_sequence=store.sequence,
        items=(
            ItemVersion(
                item_id=content.item.item_id,
                revision=1,
                content_hash=content.item.content_hash,
                evidence_generation=h.snapshot.snapshot_id,
            ),
        ),
    )
    bundle = store.export(request)
    assert bundle.markdown and bundle.csv and len(bundle.receipt.approval_event_ids) == 2


def test_unverified_x_target_refuses_before_ports(context):
    h, store, _, authority = context
    candidate = h.candidate(scope="x")
    parent = seal_content(
        item_id="recx",
        revision=1,
        kind="recommendation",
        scope="x",
        snapshot_id=h.snapshot.snapshot_id,
        text=candidate.text,
        citations=candidate.citations,
    )
    store.save(parent, actor_label="user", expected_revision=0, expected_sequence=store.sequence)
    store.decide("recx", 1, approve=True, actor_label="user", expected_sequence=store.sequence)
    with pytest.raises(PortRefusal, match="target_capability_unavailable"):
        draft(
            h.port,
            parent,
            h.snapshot,
            "Brief",
            authority=authority,
            actor_label="user",
            bindings=h.bindings(),
        )
    assert not h.generate_calls


def test_boolean_approval_flag_is_not_a_parent_authority(context):
    h, _, parent, _ = context
    authority = type(
        "ForgedAuthority", (), {"require_approved": staticmethod(lambda *args, **kwargs: True)}
    )()
    with pytest.raises(PortRefusal, match="parent_approval_required"):
        draft(
            h.port,
            parent,
            h.snapshot,
            "Brief",
            authority=authority,
            actor_label="user",
            bindings=h.bindings(),
        )
    assert not h.generate_calls


def test_parent_edit_during_generation_blocks_any_later_model_or_disclosure(context):
    h, store, parent, authority = context
    approve_parent(store)
    original = h.generate

    def generate(assembly, *, binding):
        result = original(assembly, binding=binding)
        new = seal_content(
            item_id="rec",
            revision=2,
            kind="recommendation",
            scope="linkedin",
            snapshot_id=h.snapshot.snapshot_id,
            text="Changed {{cite:er.linkedin.topic.untagged}}",
            citations=parent.item.citations,
        )
        store.save(new, actor_label="user", expected_revision=1, expected_sequence=store.sequence)
        return result

    h.port.generator = type("Generator", (), {"generate": staticmethod(generate)})()
    result = draft(
        h.port,
        parent,
        h.snapshot,
        "Brief",
        authority=authority,
        actor_label="user",
        bindings=h.bindings(),
    )
    assert result.accepted is None and not h.support_calls
    assert result.dropped[-1].codes == ("parent_approval_required",)


def test_source_generation_change_during_generation_blocks_any_later_model(context):
    h, store, parent, authority = context
    approve_parent(store)
    original = h.generate

    def generate(assembly, *, binding):
        result = original(assembly, binding=binding)
        store.activate_context("b" * 64, expected_sequence=store.sequence)
        return result

    h.port.generator = type("Generator", (), {"generate": staticmethod(generate)})()
    result = draft(
        h.port,
        parent,
        h.snapshot,
        "Brief",
        authority=authority,
        actor_label="user",
        bindings=h.bindings(),
    )
    assert result.accepted is None and not h.support_calls


def test_target_limit_repairs_once_then_preserves_supported_draft(context):
    h, store, parent, authority = context
    approve_parent(store)
    h.batches = [
        (h.candidate(scope="linkedin", text="z" * 3001 + " {{cite:er.linkedin.topic.untagged}}"),),
        (h.candidate("draft bravo", scope="linkedin"),),
    ]
    result = draft(
        h.port,
        parent,
        h.snapshot,
        "Brief",
        authority=authority,
        actor_label="user",
        bindings=h.bindings(),
    )
    assert result.accepted and result.proposed == 2
    assert result.dropped[0].codes == ("linkedin_utf16_limit",)


def test_output_hold_blocks_draft_disclosure_semantic_and_repair(context):
    h, store, parent, authority = context
    approve_parent(store)
    h.hold_support = True
    result = draft(
        h.port,
        parent,
        h.snapshot,
        "Brief",
        authority=authority,
        actor_label="user",
        bindings=h.bindings(),
    )
    assert not result.accepted and len(h.generate_calls) == 1 and not h.support_calls


def test_foreign_platform_or_changed_parent_evidence_is_not_inherited(context):
    h, store, parent, authority = context
    approve_parent(store)
    h.batches = [(h.candidate(scope="x"),), (h.candidate(scope="x"),)]
    result = draft(
        h.port,
        parent,
        h.snapshot,
        "Brief",
        authority=authority,
        actor_label="user",
        bindings=h.bindings(),
    )
    assert not result.accepted and not h.support_calls and result.proposed == 2
    assert all(value.codes == ("parent_evidence_mismatch",) for value in result.dropped)
