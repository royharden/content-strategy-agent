import csv
import hashlib
import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from content_strategy.shared.grounded.audit import AuditStore, GateError
from content_strategy.shared.grounded.validation import Policy


def test_positive_durable_two_approvals_two_formats_replay(harness):
    h = harness()
    _, draft = h.journey()
    request = h.request(draft)
    bundle = h.store.export(request)
    assert bundle.markdown and bundle.csv and not bundle.historical_replay
    assert h.store.state("draft", 1) == "exported"
    assert len(bundle.receipt.approval_event_ids) == 2
    for artifact in bundle.receipt.artifacts:
        payload = bundle.markdown if artifact.format == "md" else bundle.csv
        assert artifact.byte_length == len(payload)
        assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
    replay = h.store.export(request)
    assert replay.historical_replay and replay.receipt == bundle.receipt
    assert (replay.markdown, replay.csv) == (bundle.markdown, bundle.csv)
    assert "0.125 ratio" in bundle.csv.decode()
    second = harness()
    restarted = second.store.replay(request)
    assert restarted.receipt == bundle.receipt
    assert second.store.read_receipt("download", actor_label="user").csv == bundle.csv


def test_recommendation_required_before_draft_and_draft_approval_before_export(harness):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    draft = h.content(kind="draft", item_id="draft", parent_id="rec", parent_revision=1)
    with pytest.raises(GateError, match="current_approval_required"):
        h.save(draft)
    h.approve(rec)
    h.save(draft)
    with pytest.raises(GateError, match="current_approval_required"):
        h.store.export(h.request(draft))
    h.approve(draft)
    assert h.store.export(h.request(draft)).csv


@pytest.mark.parametrize(
    "mutation",
    [
        "screen_hold",
        "screen_not_run",
        "contradicts",
        "says_nothing",
        "unknown",
        "semantic_not_run",
        "content_hash",
        "evidence_hash",
        "policy_hash",
        "screen_edition",
    ],
)
def test_approval_screen_semantic_and_binding_fail_closed_with_positive_recovery(harness, mutation):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    if mutation.startswith("screen_") and mutation != "screen_edition":
        h.screen = mutation.removeprefix("screen_")
    elif mutation in {"contradicts", "says_nothing", "unknown", "semantic_not_run"}:
        h.semantic = "not_run" if mutation == "semantic_not_run" else mutation
    else:
        h.assessment_overrides[mutation] = (
            "different-screen" if mutation == "screen_edition" else "b" * 64
        )
    sequence = h.store.sequence
    with pytest.raises(GateError):
        h.approve(rec)
    assert h.store.sequence == sequence and h.store.state("rec", 1) == "draft"
    h.screen, h.semantic, h.assessment_overrides = "pass", "supports", {}
    assert h.approve(rec)


def test_export_rechecks_current_screen_with_fresh_pass_recovery(harness):
    h = harness()
    _, draft = h.journey()
    h.screen = "hold"
    with pytest.raises(GateError, match="screen_not_passed"):
        h.store.export(h.request(draft))
    assert h.store.state("draft", 1) == "approved"
    h.screen = "pass"
    assert h.store.export(h.request(draft)).receipt


def test_authorization_is_injected_and_actor_label_alone_grants_nothing(harness):
    h = harness()
    _, draft = h.journey()
    h.allowed = False
    with pytest.raises(GateError, match="not_authorized"):
        h.store.export(h.request(draft))
    h.allowed = True
    original = h.store.export(h.request(draft))
    h.allowed = False
    with pytest.raises(GateError, match="not_authorized"):
        h.store.replay(
            h.request(draft, expected_sequence=original.receipt.item_versions[0].revision)
        )


def test_reject_state_is_not_approval_and_explicit_boolean_required(harness):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    with pytest.raises(GateError, match="explicit_decision_required"):
        h.store.decide("rec", 1, approve=1, actor_label="user", expected_sequence=h.store.sequence)
    h.store.decide("rec", 1, approve=False, actor_label="user", expected_sequence=h.store.sequence)
    assert h.store.state("rec", 1) == "rejected"
    with pytest.raises(GateError, match="draft_state_required"):
        h.approve(rec)


def test_edits_invalidate_exact_version_and_dependent_draft_then_new_revision_can_approve(harness):
    h = harness()
    _, draft = h.journey()
    stale_request = h.request(draft)
    rec2 = h.content(revision=2, text="Changed evidence {{cite:fact}}")
    h.save(rec2)
    assert h.store.state("rec", 1) == h.store.state("draft", 1) == "draft"
    with pytest.raises(GateError):
        h.store.export(stale_request)
    with pytest.raises(GateError, match="stale_item_revision"):
        h.store.decide(
            "rec", 1, approve=True, actor_label="user", expected_sequence=h.store.sequence
        )
    h.approve(rec2)
    draft2 = h.content(
        kind="draft", item_id="draft", revision=2, parent_id="rec", parent_revision=2
    )
    h.save(draft2)
    h.approve(draft2)
    assert h.store.export(h.request(draft2)).receipt.item_versions[0].revision == 2


def test_changed_parent_citations_scope_or_revision_cannot_be_inherited(harness):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    h.approve(rec)
    second_metric = type(h.metric).model_validate(h.metric.model_dump() | {"metric_id": "another"})
    h.resolver.metrics["another"] = second_metric
    citation = rec.item.citations[0]
    altered = type(citation).model_validate(citation.model_dump() | {"metric_id": "another"})
    draft = h.content(
        kind="draft",
        item_id="draft",
        parent_id="rec",
        parent_revision=1,
        citations=(altered,),
        text="{{cite:another}}",
    )
    with pytest.raises(GateError, match="parent_evidence_mismatch"):
        h.save(draft)


def test_policy_source_changes_invalidate_and_historical_replay_never_current_approval(harness):
    h = harness()
    _, draft = h.journey()
    request = h.request(draft)
    original = h.store.export(request)
    new = harness(policy=Policy(edition="grounded-policy.v2", screen_edition="fixture.v2"))
    new.activate()
    assert new.store.state("draft", 1) == "draft"
    assert new.store.replay(request).markdown == original.markdown
    assert new.store.read_receipt("download", actor_label="user").historical_replay
    with pytest.raises(GateError):
        new.store.export(new.request(draft, idempotency_key="new-download"))
    old_sequence = new.store.sequence
    new.activate()  # Identical activation has no new effects.
    assert new.store.sequence == old_sequence
    new.store.activate_context("b" * 64, expected_sequence=new.store.sequence)
    with pytest.raises(GateError, match="stale_evidence_or_policy"):
        new.approve(draft)


def test_idempotency_full_request_conflict_and_exact_item_version_conflict(harness):
    h = harness()
    _, draft = h.journey()
    request = h.request(draft)
    h.store.export(request)
    changed = request.model_copy(update={"expected_sequence": request.expected_sequence + 1})
    with pytest.raises(GateError, match="idempotency_conflict"):
        h.store.export(changed)
    bad_version = request.items[0].model_copy(update={"content_hash": "b" * 64})
    with pytest.raises(GateError, match="export_version_mismatch"):
        h.store.export(h.request(draft, idempotency_key="other", items=(bad_version,)))


@pytest.mark.parametrize(
    "table", ["grounded_meta", "grounded_versions", "grounded_events", "grounded_receipts"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_append_only_tamper_guards(harness, table, operation):
    h = harness()
    _, draft = h.journey()
    h.store.export(h.request(draft))
    column = {
        "grounded_meta": "sha256",
        "grounded_versions": "content_hash",
        "grounded_events": "payload",
        "grounded_receipts": "request_hash",
    }[table]
    sql = (
        f"UPDATE {table} SET {column}={column}" if operation == "UPDATE" else f"DELETE FROM {table}"
    )
    with pytest.raises(sqlite3.IntegrityError, match="append_only"):
        h.store.connection.execute(sql)


def test_removed_guard_is_detected_before_use_or_restart(harness):
    h = harness()
    h.activate()
    h.store.connection.execute("DROP TRIGGER grounded_events_no_update")
    with pytest.raises(GateError, match="migration_schema_tamper"):
        h.save(h.content())
    with pytest.raises(GateError, match="migration_schema_tamper"):
        harness()


def test_formula_safe_csv_and_markdown_html_escaping(harness):
    h = harness()
    _, draft = h.journey(text="=FORMULA {{cite:fact}} <script>alert</script>", item_id="=draft")
    bundle = h.store.export(h.request(draft))
    fields = list(csv.reader(io.StringIO(bundle.csv.decode())))[1]
    assert fields[0] == "'=draft" and fields[3].startswith("'=FORMULA")
    assert b"<script>" not in bundle.markdown and b"&lt;script&gt;" in bundle.markdown


@pytest.mark.parametrize("prefix", ["\t=", " \r=", "\x00=", "\ufeff=", "\u200b=", "@", "+", "-"])
def test_hidden_formula_prefixes_are_neutralized_in_actual_csv(harness, prefix):
    h = harness()
    _, draft = h.journey(text=prefix + "FORMULA {{cite:fact}}")
    bundle = h.store.export(h.request(draft))
    cell = list(csv.reader(io.StringIO(bundle.csv.decode())))[1][3]
    assert cell.startswith("'")


def test_no_receipt_on_oversized_bundle_and_exact_limit_is_accepted(harness, monkeypatch):
    import content_strategy.shared.grounded.audit as module

    h = harness()
    _, draft = h.journey()
    request = h.request(draft)
    # Roll back a before-commit probe to obtain the real output size, then set exact boundary.
    sizes = []

    def probe(stage):
        if stage == "before_commit":
            sizes.append(
                h.store.connection.execute(
                    "SELECT length(markdown)+length(csv) FROM grounded_receipts"
                ).fetchone()[0]
            )
            raise RuntimeError("probe")

    h.store.fault = probe
    with pytest.raises(RuntimeError):
        h.store.export(request)
    assert h.store.connection.execute("SELECT COUNT(*) FROM grounded_receipts").fetchone()[0] == 0
    h.store.fault = None
    monkeypatch.setattr(module, "MAX_BUNDLE_BYTES", sizes[0] - 1)
    with pytest.raises(GateError, match="bundle_byte_limit"):
        h.store.export(request)
    assert h.store.state("draft", 1) == "approved"
    monkeypatch.setattr(module, "MAX_BUNDLE_BYTES", sizes[0])
    assert h.store.export(request).receipt


def test_actual_two_mib_bundle_limit_rejects_atomically(harness):
    from content_strategy.shared.grounded.audit import _version

    h = harness()
    _, first = h.journey(text="x" * 16000 + " {{cite:fact}}")
    drafts = [first]
    for index in range(65):
        draft = h.content(
            kind="draft",
            item_id=f"draft{index}",
            parent_id="rec",
            parent_revision=1,
            text="x" * 16000 + " {{cite:fact}}",
        )
        h.save(draft)
        h.approve(draft)
        drafts.append(draft)
    before = h.store.sequence
    with pytest.raises(GateError, match="bundle_byte_limit"):
        h.store.export(h.request(first, items=tuple(_version(draft) for draft in drafts)))
    assert h.store.sequence == before
    assert h.store.connection.execute("SELECT COUNT(*) FROM grounded_receipts").fetchone()[0] == 0
    assert h.store.export(h.request(first)).receipt


@pytest.mark.parametrize(
    "table", ["grounded_meta", "grounded_versions", "grounded_events", "grounded_receipts"]
)
def test_replace_cannot_bypass_append_only_even_without_recursive_triggers(harness, table):
    h = harness()
    _, draft = h.journey()
    h.store.export(h.request(draft))
    h.store.connection.execute("PRAGMA recursive_triggers=OFF")
    with pytest.raises(sqlite3.IntegrityError, match="append_only"):
        h.store.connection.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")


def test_sequence_and_revision_cas_prevent_lost_decisions(harness):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    initial = h.store.sequence
    h.approve(rec)
    with pytest.raises(GateError, match="sequence_conflict"):
        h.store.decide("rec", 1, approve=False, actor_label="user", expected_sequence=initial)
    with pytest.raises(GateError, match="revision_conflict"):
        h.save(rec)


def test_actual_two_connection_race_allows_only_one_decision(harness, tmp_path):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    expected = h.store.sequence
    barrier = Barrier(2)

    def compete(approve):
        store = AuditStore(
            tmp_path / "authority.sqlite3",
            namespace="test",
            policy=h.policy,
            resolver=h.resolver,
            authorize=lambda *args: True,
            assess=h.assess,
        )
        barrier.wait(timeout=5)
        try:
            store.decide("rec", 1, approve=approve, actor_label="user", expected_sequence=expected)
            return "committed"
        except GateError as error:
            return str(error)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compete, (True, False)))
    assert sorted(results) == ["committed", "sequence_conflict"]


def test_namespace_isolation_bounded_identifier_and_no_path_receipt_lookup(harness):
    h = harness()
    _, draft = h.journey()
    request = h.request(draft)
    h.store.export(request)
    other = harness(namespace="other")
    with pytest.raises(GateError, match="unknown_receipt"):
        other.store.replay(request)
    with pytest.raises(GateError, match="invalid_namespace"):
        harness(namespace="../other")
    with pytest.raises(GateError, match="unknown_receipt"):
        h.store.read_receipt("../file.csv", actor_label="user")
    h.allowed = False
    with pytest.raises(GateError, match="not_authorized"):
        h.store.read_receipt("download", actor_label="user")


def test_audit_bindings_and_automatic_events_do_not_impersonate_human(harness):
    h = harness()
    h.journey()
    rows = h.store.connection.execute(
        "SELECT action,payload FROM grounded_events ORDER BY sequence"
    ).fetchall()
    approvals = [json.loads(payload) for action, payload in rows if action == "approve"]
    assert len(approvals) == 2
    assert all(
        p["actor_label"] == "user"
        and p["policy_hash"] == h.policy.digest
        and p["validator_version"] == h.policy.validator_version
        for p in approvals
    )
    assert all(p["assessment"]["screen_status"] == "pass" for p in approvals)
    assert [action for action, _ in rows] == ["context", "create", "approve", "create", "approve"]
