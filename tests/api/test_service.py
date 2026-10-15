"""Development boundary tests, not independent fixture/evaluation evidence."""

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from content_strategy.api import LocalReviewService, Selection
from content_strategy.metrics import AnalysisConfig
from content_strategy.shared.grounded.audit import GateError
from content_strategy.shared.grounded.identity import canonical_decimal
from content_strategy.shared.grounded.models import ItemVersion, MetricCitation
from content_strategy.shared.grounded.validation import Assessment, Policy, seal_content
from content_strategy.storage import StorageError


def source():
    return (
        "post_id,date,platform,text,impressions,likes,comments,shares\n"
        + "".join(f"p{i},2026-10-14T01:00:00+02:00,linkedin,hello,100,10,0,0\n" for i in range(6))
    ).encode()


def version(content):
    return ItemVersion(
        item_id=content.item.item_id,
        revision=content.item.revision,
        content_hash=content.item.content_hash,
        evidence_generation=content.item.snapshot_id,
    )


@dataclass
class Harness:
    service: LocalReviewService
    denied: set
    seen: list
    selection: Selection

    def content(self, *, kind="recommendation", item_id="rec", revision=1, **changes):
        retained = self.service.report(self.selection)
        metric = next(m for m in retained.report.snapshot.metrics if m.status == "ok")
        return seal_content(
            item_id=item_id,
            revision=revision,
            kind=kind,
            scope=metric.scope,
            snapshot_id=metric.snapshot_id,
            text="Observed {{cite:" + metric.metric_id + "}}",
            citations=(
                MetricCitation(
                    snapshot_id=metric.snapshot_id,
                    metric_id=metric.metric_id,
                    scope=metric.scope,
                    quoted_value=canonical_decimal(metric.value),
                    unit=metric.unit,
                ),
            ),
            **changes,
        )

    def save(self, content):
        return self.service.save(
            self.selection,
            content,
            expected_revision=content.item.revision - 1,
            expected_sequence=self.service.sequence(self.selection),
        )

    def approve(self, content):
        return self.service.decide(
            self.selection,
            version(content),
            approve=True,
            expected_sequence=self.service.sequence(self.selection),
        )

    def journey(self):
        self.service.activate(self.selection, expected_sequence=0)
        rec = self.content()
        self.save(rec)
        self.approve(rec)
        draft = self.content(kind="draft", item_id="draft", parent_id="rec", parent_revision=1)
        self.save(draft)
        self.approve(draft)
        return rec, draft


@pytest.fixture
def make(tmp_path):
    def create(namespace="local", denied=None, import_source=True):
        denied = set() if denied is None else denied
        seen = []

        def authorize(actor, action, content):
            seen.append((actor, action, content))
            return actor == "host-user" and action not in denied

        def assess(checked, policy):
            # Explicit synthetic test callback, never a production default/review.
            return Assessment(
                content_hash=checked.content.item.content_hash,
                evidence_hash=checked.evidence_hash,
                policy_hash=policy.digest,
                screen_edition=policy.screen_edition,
                screen_status="pass",
                semantic_status="supports",
            )

        service = LocalReviewService(
            tmp_path / "review.sqlite3",
            namespace=namespace,
            actor_label="host-user",
            policy=Policy(screen_edition="injected-test.v1"),
            authorize=authorize,
            assess=assess,
        )
        selection = None
        if import_source:
            retained = service.import_csv(source())
            selection = Selection(
                dataset_id=retained.dataset_id, snapshot_id=retained.report.snapshot.snapshot_id
            )
        return Harness(service, denied, seen, selection)

    return create


def test_actual_retention_two_approval_export_restart_and_historical_receipt(make):
    h = make()
    assert h.service.sequence(h.selection) == 0  # Import did not activate or approve.
    rec, draft = h.journey()
    bundle = h.service.export(
        h.selection,
        idempotency_key="download",
        items=(version(draft),),
        expected_sequence=h.service.sequence(h.selection),
    )
    assert bundle.csv and bundle.markdown and len(bundle.receipt.approval_event_ids) == 2
    restarted = make()
    assert restarted.selection == h.selection
    replay = restarted.service.download_receipt(h.selection, "download")
    assert replay.historical_replay and replay.receipt == bundle.receipt
    h.save(h.content(revision=2))
    assert h.service.download_receipt(h.selection, "download").csv == bundle.csv
    with pytest.raises(GateError):
        h.service.export(
            h.selection,
            idempotency_key="new-download",
            items=(version(draft),),
            expected_sequence=h.service.sequence(h.selection),
        )
    assert h.service.read(h.selection, version(rec)) == rec  # Historical read, no approval token.


@pytest.mark.parametrize("action", ["import_csv", "activate_context", "read_report"])
def test_source_authorization_is_before_mutation_or_read(make, action):
    h = make(import_source=action != "import_csv")
    h.denied.add(action)
    with pytest.raises(GateError, match="not_authorized"):
        if action == "import_csv":
            h.service.import_csv(source())
        elif action == "activate_context":
            h.service.activate(h.selection, expected_sequence=0)
        else:
            h.service.report(h.selection)
    if action == "import_csv":
        assert not h.service.database.exists()
    else:
        h.denied.clear()
        assert h.service.sequence(h.selection) == 0


@pytest.mark.parametrize("action", ["save", "approve", "read_content", "export", "read_receipt"])
def test_item_callbacks_are_required_at_actual_authority_boundary(make, action):
    h = make()
    rec, draft = h.journey()
    bundle = h.service.export(
        h.selection,
        idempotency_key="old",
        items=(version(draft),),
        expected_sequence=h.service.sequence(h.selection),
    )
    h.denied.add(action)
    with pytest.raises(GateError, match="not_authorized"):
        if action == "save":
            h.save(h.content(revision=2))
        elif action == "approve":
            changed = h.content(item_id="another")
            h.save(changed)
            h.approve(changed)
        elif action == "read_content":
            h.service.read(h.selection, version(rec))
        elif action == "read_receipt":
            h.service.download_receipt(h.selection, "old")
        else:
            h.service.export(
                h.selection,
                idempotency_key="new",
                items=(version(draft),),
                expected_sequence=h.service.sequence(h.selection),
            )
    assert all(actor == "host-user" for actor, _, _ in h.seen)
    assert bundle.receipt


def test_selection_namespace_and_exact_version_mismatch_fail_before_decision(make):
    h = make()
    rec, _ = h.journey()
    other = make(namespace="other", import_source=False)
    with pytest.raises(StorageError):
        other.service.report(h.selection)
    wrong = version(rec).model_copy(update={"content_hash": "f" * 64})
    sequence = h.service.sequence(h.selection)
    with pytest.raises(GateError, match="version_mismatch"):
        h.service.decide(h.selection, wrong, approve=True, expected_sequence=sequence)
    assert h.service.sequence(h.selection) == sequence
    wrong = version(rec).model_copy(update={"evidence_generation": "f" * 64})
    with pytest.raises(GateError, match="selection_generation_mismatch"):
        h.service.read(h.selection, wrong)
    with pytest.raises(ValidationError):
        Selection(
            dataset_id=h.selection.dataset_id, snapshot_id=h.selection.snapshot_id, actor="root"
        )


def test_stale_sequence_context_change_and_missing_parent_stop_writes(make):
    h = make()
    h.service.activate(h.selection, expected_sequence=0)
    rec = h.content()
    with pytest.raises(GateError, match="sequence_conflict"):
        h.service.save(h.selection, rec, expected_revision=0, expected_sequence=0)
    h.save(rec)
    draft = h.content(kind="draft", item_id="draft", parent_id="rec", parent_revision=1)
    with pytest.raises(GateError, match="current_approval_required"):
        h.save(draft)
    h.approve(rec)
    retained = h.service.import_csv(source(), config=AnalysisConfig("fixed-utc"))
    newer = Selection(
        dataset_id=retained.dataset_id, snapshot_id=retained.report.snapshot.snapshot_id
    )
    h.service.activate(newer, expected_sequence=h.service.sequence(h.selection))
    with pytest.raises(GateError, match="stale_evidence_or_policy"):
        h.save(draft)
    with pytest.raises(GateError, match="selection_generation_mismatch"):
        h.service.save(newer, rec, expected_revision=0, expected_sequence=h.service.sequence(newer))


def test_no_callbacks_no_service_and_no_database_creation(make, tmp_path):
    with pytest.raises(GateError, match="host_callbacks_required"):
        LocalReviewService(
            tmp_path / "none",
            namespace="local",
            actor_label="user",
            policy=Policy(screen_edition="test"),
            authorize=None,
            assess=None,
        )
    h = make(import_source=False)
    selection = Selection(dataset_id="s9-dataset-" + "a" * 32, snapshot_id="a" * 64)
    with pytest.raises(GateError, match="unknown_source"):
        h.service.report(selection)
    assert not h.service.database.exists()


def test_intervening_edit_after_exact_read_cannot_approve_old_version(make, monkeypatch):
    h = make()
    h.service.activate(h.selection, expected_sequence=0)
    rec = h.content()
    h.save(rec)
    sequence = h.service.sequence(h.selection)
    original_read = h.service.read

    def intervening_read(selection, requested):
        result = original_read(selection, requested)
        h.save(h.content(revision=2))
        return result

    monkeypatch.setattr(h.service, "read", intervening_read)
    with pytest.raises(GateError, match="sequence_conflict"):
        h.service.decide(h.selection, version(rec), approve=True, expected_sequence=sequence)


def test_assessment_callback_failure_never_becomes_implicit_support(make):
    h = make()
    h.service.activate(h.selection, expected_sequence=0)
    rec = h.content()
    h.save(rec)
    sequence = h.service.sequence(h.selection)
    original_assess = h.service.assess

    def unavailable(*args):
        raise GateError("required_assessment_unavailable")

    h.service.assess = unavailable
    with pytest.raises(GateError, match="required_assessment_unavailable"):
        h.approve(rec)
    assert h.service.sequence(h.selection) == sequence
    h.service.assess = original_assess
    assert h.approve(rec)
