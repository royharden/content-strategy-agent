"""Valid/negative wire, generated schema and moved generic-consumer controls."""

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from content_strategy.shared.grounded import (
    ApprovalEvent,
    ArtifactDigest,
    ExportReceipt,
    GroundedItem,
    ItemVersion,
    Metric,
    MetricCitation,
    MetricSnapshot,
    SnapshotIdentity,
    TagProvenance,
    ValidationFailure,
    ValidationReport,
)

REPO = Path(__file__).resolve().parents[2]
HASH = "a" * 64
OTHER = "b" * 64
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def metric(**changes):
    return Metric(
        **(
            {
                "metric_id": "rate.topic.example",
                "snapshot_id": HASH,
                "scope": "example-scope",
                "definition": "A declared ratio, not computed by this schema",
                "value": "0.125",
                "unit": "ratio",
                "sample_size": 5,
                "computed_by": "future.rate.v1",
                "status": "ok",
            }
            | changes
        )
    )


def version():
    return ItemVersion(item_id="item-1", revision=1, content_hash=HASH, evidence_generation=OTHER)


def test_exact_decimal_json_roundtrip_is_string_and_never_display_rounded():
    original = metric(value=Decimal("0.12500000"))
    assert json.loads(original.model_dump_json())["value"] == "0.125"
    assert Metric.model_validate_json(original.model_dump_json()) == original
    assert metric(value="0.12500001").value != original.value


def test_json_number_is_not_promoted_to_an_exact_value():
    payload = json.loads(metric().model_dump_json())
    payload["value"] = 0.125
    with pytest.raises(ValidationError):
        Metric.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "value", [0.125, 1, True, "NaN", "Infinity", "1e-3", "0.123456789", Decimal("NaN")]
)
def test_nonexact_decimal_coercion_and_overprecision_fail(value):
    with pytest.raises(ValidationError):
        metric(value=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_size": True},
        {"sample_size": "5"},
        {"sample_size": -1},
        {"sample_size": 5.0},
        {"schema_version": True},
        {"schema_version": "1"},
        {"schema_version": 2},
        {"status": "approved"},
        {"extra": "undeclared"},
        {"snapshot_id": "A" * 64},
        {"status": "unavailable", "value": "0", "status_reason": "missing"},
        {"status": "insufficient_data"},
        {"value": None},
    ],
)
def test_strict_tags_unknown_fields_counts_hashes_and_status_consistency(changes):
    with pytest.raises(ValidationError):
        metric(**changes)


def test_unavailable_and_low_sample_are_data_not_citable_validity_claims():
    missing = metric(status="unavailable", value=None, status_reason="missing_time", sample_size=0)
    small = metric(status="insufficient_data", status_reason="minimum_n", sample_size=1)
    assert missing.value is None
    assert small.sample_size == 1
    # min_n is a future policy check, not hard-coded into generic structural schemas.
    assert metric(sample_size=1).status == "ok"


def test_snapshot_metadata_timestamp_does_not_change_generation():
    identity = SnapshotIdentity(
        dataset_fingerprint=HASH,
        tag_provenance=(),
        config_json='{"minimum_n":5}',
        compute_version="metrics.v1",
    )
    first = MetricSnapshot(
        identity=identity,
        snapshot_id=identity.snapshot_id,
        created_at=NOW,
        metrics=(metric(snapshot_id=identity.snapshot_id),),
    )
    second = MetricSnapshot.model_validate(
        first.model_dump(mode="python") | {"created_at": NOW + timedelta(days=1)}
    )
    assert first.snapshot_id == second.snapshot_id == identity.snapshot_id
    for changes in [
        {"snapshot_id": HASH},
        {"metrics": (metric(),)},
        {"created_at": NOW.replace(tzinfo=None)},
        {"metrics": first.metrics * 2},
    ]:
        with pytest.raises(ValidationError):
            MetricSnapshot.model_validate(first.model_dump(mode="python") | changes)


def test_thresholds_and_parent_revision_shape_are_strict():
    with pytest.raises(ValidationError):
        TagProvenance(
            source_id="p",
            field="topic",
            value="test",
            method="test",
            taxonomy_version="v1",
            threshold="1.00000001",
        )
    citation = MetricCitation(
        snapshot_id=HASH, metric_id="unknown", scope="example", quoted_value="0.1", unit="ratio"
    )
    fields = {
        "item_id": "i",
        "revision": 1,
        "kind": "rfp-answer",
        "scope": "example",
        "snapshot_id": HASH,
        "text": "Proposed answer",
        "citations": (citation,),
        "content_hash": OTHER,
    }
    assert GroundedItem(**fields).citations[0].key.evidence_id == "unknown"
    with pytest.raises(ValidationError):
        GroundedItem(**fields, parent_id="parent")


def test_structural_approval_and_receipt_do_not_claim_authentication_or_execute():
    event = ApprovalEvent(
        event_id="unverified-event",
        sequence=1,
        item=version(),
        from_state="draft",
        to_state="approved",
        actor_label="unverified-demo-label",
        at_utc=NOW,
        policy_sha256=HASH,
    )
    assert event.to_state == "approved"  # Untrusted record data, not approval enforcement.
    assert not hasattr(event, "authorize")
    receipt = ExportReceipt(
        export_id="unverified-receipt",
        idempotency_key="k",
        request_hash=HASH,
        item_versions=(version(),),
        artifacts=(
            ArtifactDigest(format="md", sha256=HASH, byte_length=1),
            ArtifactDigest(format="csv", sha256=OTHER, byte_length=1),
        ),
        approval_event_ids=(event.event_id,),
        at_utc=NOW,
    )
    assert not hasattr(receipt, "export")
    for changes in [
        {"artifacts": receipt.artifacts[:1]},
        {"artifacts": receipt.artifacts[:1] * 2},
        {"approval_event_ids": ()},
        {"item_versions": receipt.item_versions * 2},
        {"at_utc": NOW.replace(tzinfo=None)},
    ]:
        with pytest.raises(ValidationError):
            ExportReceipt.model_validate(receipt.model_dump(mode="python") | changes)


def test_oversize_receipt_and_non_utc_event_fail_shape_validation():
    with pytest.raises(ValidationError):
        ExportReceipt(
            export_id="e",
            idempotency_key="k",
            request_hash=HASH,
            item_versions=(version(),),
            artifacts=(
                ArtifactDigest(format="md", sha256=HASH, byte_length=2 * 1024 * 1024),
                ArtifactDigest(format="csv", sha256=OTHER, byte_length=1),
            ),
            approval_event_ids=("e",),
            at_utc=NOW,
        )
    with pytest.raises(ValidationError):
        ApprovalEvent(
            event_id="e",
            sequence=1,
            item=version(),
            from_state="draft",
            to_state="approved",
            actor_label="demo",
            at_utc=NOW.astimezone(timezone(timedelta(hours=1))),
            policy_sha256=HASH,
        )


def test_report_consistency_is_not_a_semantic_judge():
    report = ValidationReport(
        item_id="i",
        revision=1,
        snapshot_id=HASH,
        structural_status="valid",
        failures=(),
        semantic_status="not_run",
        validator_version="shape-only",
    )
    assert report.semantic_status == "not_run"
    with pytest.raises(ValidationError):
        ValidationReport.model_validate(report.model_dump() | {"structural_status": "invalid"})
    failure = ValidationFailure(code="unknown-reference")
    assert ValidationReport.model_validate(
        report.model_dump() | {"structural_status": "invalid", "failures": (failure,)}
    ).failures


def test_generated_schemas_are_reproducible_and_drift_check_can_fail():
    script = REPO / "scripts/export_schemas.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    bundle = json.loads((REPO / "schemas/grounded-v1.json").read_text())
    assert len(bundle["models"]) == 13
    assert bundle["models"]["Metric"]["additionalProperties"] is False
    with tempfile.TemporaryDirectory() as directory:
        altered = Path(directory) / "wrong.json"
        altered.write_text("{}")
        result = subprocess.run(
            [sys.executable, str(script), "--check", "--output", str(altered)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1


def test_detached_module_supports_nonreceipt_m3_m8_toy_consumers():
    with tempfile.TemporaryDirectory(prefix="grounded detached ") as directory:
        root = Path(directory)
        target = root / "toy_consumer/shared"
        target.mkdir(parents=True)
        (root / "toy_consumer/__init__.py").write_text("")
        (target / "__init__.py").write_text("")
        shutil.copytree(REPO / "src/content_strategy/shared/grounded", target / "grounded")
        program = """
import sys
from dataclasses import dataclass
class RejectOwnerImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "content_strategy" or fullname.startswith("content_strategy."):
            raise ImportError("Owner application is deliberately unavailable")
sys.meta_path.insert(0, RejectOwnerImports())
sys.path.insert(0, sys.argv[1])
from toy_consumer.shared.grounded import EvidenceKey, EvidenceResolver
@dataclass(frozen=True)
class Passage:
    text: str
class CorpusResolver:
    def resolve(self, key: EvidenceKey) -> Passage | None:
        return Passage("Synthetic proposal evidence") if key.scope == "rfp" else None
class QueueResolver:
    def resolve(self, key: EvidenceKey) -> tuple[str, int] | None:
        return (key.evidence_id, 3) if key.scope == "gateway" else None
corpus: EvidenceResolver[Passage] = CorpusResolver()
queue: EvidenceResolver[tuple[str, int]] = QueueResolver()
assert corpus.resolve(EvidenceKey(generation="a"*64,evidence_id="section-1",scope="rfp")).text
queue_key = EvidenceKey(generation="a"*64,evidence_id="request-1",scope="gateway")
assert queue.resolve(queue_key) == ("request-1",3)
assert corpus.resolve(EvidenceKey(generation="b"*64,evidence_id="x",scope="absent")) is None
assert EvidenceKey.__module__.startswith("toy_consumer.")
print("detached generic M3/M8 model/protocol consumers passed; no authorization performed")
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", program, str(root)],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=root,
        )
        assert result.returncode == 0, result.stderr
        assert "detached generic M3/M8" in result.stdout
