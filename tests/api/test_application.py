"""Synthetic local sourceâ†’actual mock executionâ†’durable proof/review development controls."""

import sqlite3
from dataclasses import dataclass, replace

import pytest

from content_strategy.api.application import PlanningHost
from content_strategy.api.service import LocalReviewService, Selection
from content_strategy.pipeline.assembly import recommendation_content
from content_strategy.pipeline.ports import Candidate
from content_strategy.runtime.proofs import ProofStore
from content_strategy.shared.grounded.audit import GateError
from content_strategy.shared.grounded.identity import canonical_decimal
from content_strategy.shared.grounded.models import MetricCitation
from content_strategy.shared.grounded.validation import Policy, seal_content
from content_strategy.shared.screen import ScreenPolicy
from content_strategy.shared.screen.models import HAZARDS


@dataclass
class App:
    host: PlanningHost
    selection: Selection
    candidates: tuple
    verdicts: dict
    denied: set

    def run(self, **changes):
        kwargs = dict(
            screen_scores=dict.fromkeys(HAZARDS, 0.01),
            support_verdicts=self.verdicts,
            expected_sequence=self.host.review.sequence(self.selection),
        )
        kwargs.update(changes)
        return self.host.run_authored_plan(
            self.selection, "An authored plan", self.candidates, **kwargs
        )


@pytest.fixture
def make(tmp_path):
    def create():
        database = tmp_path / "review.sqlite3"
        denied = set()
        proofs = ProofStore(database, namespace="local")
        policy = ScreenPolicy(
            "s9-synthetic-mock.v1",
            "typed",
            profile_id="s9-synthetic-smoke.v1",
            thresholds=dict.fromkeys(HAZARDS, 0.35),
            threshold_provenance="exploratory_seed",
        )
        review = LocalReviewService(
            database,
            namespace="local",
            actor_label="host-human",
            policy=Policy(screen_edition=policy.sha256),
            authorize=lambda actor, action, content: actor == "host-human" and action not in denied,
            assess=proofs.assess,
        )
        payload = b"post_id,date,platform,text,impressions,likes,comments,shares\n" + b"".join(
            f"p{i},2026-01-01,linkedin,hello,10,2,0,0\n".encode() for i in range(5)
        )
        retained = review.import_csv(payload)
        selection = Selection(
            dataset_id=retained.dataset_id, snapshot_id=retained.report.snapshot.snapshot_id
        )
        review.activate(selection, expected_sequence=0)
        metric = next(
            m
            for m in retained.report.snapshot.metrics
            if m.metric_id == "er.linkedin.topic.untagged"
        )
        candidates = tuple(
            Candidate(
                scope="linkedin",
                text=word + " {{cite:" + metric.metric_id + "}}",
                citations=(
                    MetricCitation(
                        snapshot_id=metric.snapshot_id,
                        metric_id=metric.metric_id,
                        scope=metric.scope,
                        quoted_value=canonical_decimal(metric.value),
                        unit=metric.unit,
                    ),
                ),
            )
            for word in ("alpha", "bravo", "charlie", "delta", "echo")
        )
        verdicts = {
            recommendation_content(c, selection.snapshot_id).item.item_id: "supports"
            for c in candidates
        }
        host = PlanningHost(
            review, proofs, call_database=tmp_path / "calls.sqlite3", screen_policy=policy
        )
        return App(host, selection, candidates, verdicts, denied)

    return create


def reopen(app):
    old = app.host.review
    proofs = ProofStore(old.database, namespace=old.namespace)
    return LocalReviewService(
        old.database,
        namespace=old.namespace,
        actor_label=old.actor_label,
        policy=old.policy,
        authorize=old.authorize,
        assess=proofs.assess,
    )


def test_actual_source_plan_proofs_save_preview_manual_decision_and_restart(make):
    app = make()
    result = app.run()
    assert len(result.versions) == 5 and not result.underfilled
    assert result.execution_origin == "authored_synthetic_mock"
    assert not hasattr(result, "bodies")
    review = reopen(app)
    version = result.versions[0]
    checked, assessment, sequence = review.preview(
        app.selection, version, expected_sequence=result.sequence
    )
    assert checked.content.item.content_hash == version.content_hash
    assert assessment.screen_status == "pass" and assessment.semantic_status == "supports"
    assert {row.state for row in review.history(app.selection)} == {"draft"}
    review.decide(app.selection, version, approve=True, expected_sequence=sequence)
    assert any(row.state == "approved" for row in reopen(app).history(app.selection))
    with sqlite3.connect(review.database) as db:
        assert db.execute("SELECT count(*) FROM mock_execution_proofs").fetchone()[0] == 5


def test_structurally_valid_content_without_actual_proof_cannot_be_previewed(make):
    app = make()
    content = recommendation_content(app.candidates[0], app.selection.snapshot_id)
    review = app.host.review
    sequence = review.save(
        app.selection,
        content,
        expected_revision=0,
        expected_sequence=review.sequence(app.selection),
    )
    from content_strategy.shared.grounded.models import ItemVersion

    version = ItemVersion(
        item_id=content.item.item_id,
        revision=1,
        content_hash=content.item.content_hash,
        evidence_generation=app.selection.snapshot_id,
    )
    with pytest.raises(GateError, match="proof_schema_unavailable"):
        review.preview(app.selection, version, expected_sequence=sequence)


@pytest.mark.parametrize("action", ["plan", "save", "read_context"])
def test_actual_host_permissions_are_required(make, action):
    app = make()
    app.denied.add(action)
    with pytest.raises(GateError, match="not_authorized"):
        app.run()
    assert not app.host.review.history(app.selection)


def test_mid_generation_context_change_refuses_before_any_proof_or_content_write(make, monkeypatch):
    app = make()
    from content_strategy.runtime.mock import MockPlan

    original = MockPlan.run

    def run(runtime):
        result = original(runtime)
        review = app.host.review
        changed = review.import_csv(
            b"post_id,date,platform,text,impressions,likes,comments,shares\n"
            b"new,2026-01-02,linkedin,different,10,2,0,0\n"
        )
        other = Selection(
            dataset_id=changed.dataset_id, snapshot_id=changed.report.snapshot.snapshot_id
        )
        review.activate(other, expected_sequence=review.sequence(app.selection))
        return result

    monkeypatch.setattr(MockPlan, "run", run)
    with pytest.raises(GateError):
        app.run()
    assert not app.host.review.history(app.selection)
    with sqlite3.connect(app.host.review.database) as db:
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='mock_execution_proofs'"
        ).fetchall()


def test_unassessed_edit_and_changed_policy_cannot_reuse_old_proof(make):
    app = make()
    result = app.run()
    review = app.host.review
    content = review.read(app.selection, result.versions[0])
    changes = content.item.model_dump(mode="python", exclude={"content_hash"})
    changes.update(text="Edited " + content.item.text, revision=2)
    edited = seal_content(**changes)
    sequence = review.save(
        app.selection, edited, expected_revision=1, expected_sequence=result.sequence
    )
    version = result.versions[0].model_copy(
        update={"revision": 2, "content_hash": edited.item.content_hash}
    )
    with pytest.raises(GateError, match="assessment_unavailable"):
        review.preview(app.selection, version, expected_sequence=sequence)


def test_proof_schema_and_append_only_triggers_are_enforced(make):
    app = make()
    result = app.run()
    database = app.host.review.database
    with sqlite3.connect(database) as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable_mock_proof"):
            db.execute("DELETE FROM mock_execution_proofs")
        with pytest.raises(sqlite3.IntegrityError, match="immutable_mock_proof"):
            db.execute("UPDATE mock_execution_proofs SET payload='{}'")
        db.execute("DROP TRIGGER mock_execution_proofs_no_update")
    with pytest.raises(GateError, match="proof_schema_unavailable"):
        reopen(app).preview(app.selection, result.versions[0], expected_sequence=result.sequence)


def test_inserted_corrupt_proof_fails_even_when_original_receipt_exists(make):
    app = make()
    result = app.run()
    with sqlite3.connect(app.host.review.database) as db:
        db.execute(
            "INSERT INTO mock_execution_proofs "
            "(namespace,content_hash,evidence_hash,policy_hash,screen_edition,payload,sha256) "
            "SELECT namespace,content_hash,evidence_hash,policy_hash,screen_edition,'{}',sha256 "
            "FROM mock_execution_proofs ORDER BY sequence LIMIT 1"
        )
    with pytest.raises(GateError, match="invalid_mock_proof"):
        reopen(app).preview(app.selection, result.versions[0], expected_sequence=result.sequence)


@pytest.mark.parametrize("change", ["policy", "namespace", "evidence"])
def test_exact_proof_cannot_cross_policy_namespace_or_evidence(make, change):
    app = make()
    result = app.run()
    review = app.host.review
    checked, _, _ = review.preview(
        app.selection, result.versions[0], expected_sequence=result.sequence
    )
    policy = review.policy
    proofs = app.host.proofs
    if change == "policy":
        policy = policy.model_copy(update={"screen_edition": "different-screen.v1"})
    elif change == "namespace":
        proofs = ProofStore(review.database, namespace="other")
    else:
        checked = replace(checked, evidence_hash="b" * 64)
    with pytest.raises(GateError, match="assessment_unavailable"):
        proofs.assess(checked, policy)


def test_actual_screen_hold_creates_no_proof_content_or_automatic_decision(make):
    app = make()
    result = app.run(screen_scores=dict.fromkeys(HAZARDS, 0.9))
    assert result.underfilled and not result.versions and result.dropped_codes
    assert result.sequence == 1
    assert not app.host.review.history(app.selection)
    with sqlite3.connect(app.host.review.database) as db:
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='mock_execution_proofs'"
        ).fetchall()
