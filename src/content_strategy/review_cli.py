"""Terminal journey over the same durable review authority used by the HTTP host."""

import json
import tempfile
from pathlib import Path
from uuid import uuid4

from .api.service import Selection
from .ingest import MAX_BYTES, ingest_csv
from .metrics import AnalysisConfig
from .runtime.examples import authored_draft_input, authored_plan_inputs
from .runtime.local import local_host
from .shared.screen.models import HAZARDS


def _emit(value):
    # JSON escaping prevents imported labels/content from injecting terminal controls.
    print(json.dumps(value, sort_keys=True))


def _confirm(action):
    try:
        return input(f"Type {action} to continue (anything else cancels): ").strip() == action
    except EOFError:
        return False


def _preview(review, selection, version, sequence):
    checked, assessment, sequence = review.preview(selection, version, expected_sequence=sequence)
    _emit(
        {
            "kind": checked.content.item.kind,
            "version": version.model_dump(mode="json"),
            "text": checked.rendered,
            "assessment": assessment.model_dump(mode="json"),
        }
    )
    return sequence


def _download(bundle, output_dir: Path):
    """Copies come only from a committed receipt; never overwrite user files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="approved-", dir=output_dir))
    for name, payload in (("content.md", bundle.markdown), ("content.csv", bundle.csv)):
        with (folder / name).open("xb") as stream:
            stream.write(payload)
    _emit(
        {
            "receipt": bundle.receipt.model_dump(mode="json"),
            "historical_replay": bundle.historical_replay,
            "markdown": str((folder / "content.md").resolve()),
            "csv": str((folder / "content.csv").resolve()),
        }
    )


def review_command(arguments):
    with arguments.file.open("rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    ingest_csv(payload)  # Refuse malformed input before creating any database.
    host = local_host(arguments.database, arguments.call_database, arguments.namespace)
    review = host.review
    retained = review.import_csv(payload, config=AnalysisConfig(arguments.clock))
    selection = Selection(
        dataset_id=retained.dataset_id, snapshot_id=retained.report.snapshot.snapshot_id
    )
    _emit(
        {
            "execution_origin": "authored_synthetic_mock",
            "quality_measurement": False,
            "model_calls": False,
            "selection": selection.model_dump(mode="json"),
            "metrics": [m.model_dump(mode="json") for m in retained.report.snapshot.metrics],
        }
    )
    # Activation can invalidate old decisions when the evidence/policy changed.
    if not _confirm("activate"):
        return _cancel()
    sequence = review.activate(selection, expected_sequence=review.sequence(selection))
    candidates, verdicts = authored_plan_inputs(retained.report.snapshot)
    if not candidates:
        _emit({"status": "insufficient_citable_data", "exported": False})
        return 0
    plan = host.run_authored_plan(
        selection,
        arguments.brief,
        candidates,
        screen_scores=dict.fromkeys(HAZARDS, 0.01),
        support_verdicts=verdicts,
        expected_sequence=sequence,
    )
    _emit({"recommendations": len(plan.versions), "underfilled": plan.underfilled})
    if not plan.versions:
        _emit({"status": "no_valid_recommendations", "exported": False})
        return 0
    for number, version in enumerate(plan.versions, 1):
        _emit({"recommendation": number})
        _preview(review, selection, version, plan.sequence)
    try:
        chosen = int(input("Recommendation number to draft (anything else cancels): "))
    except (ValueError, EOFError):
        return _cancel()
    if not 1 <= chosen <= len(plan.versions):
        return _cancel()
    parent = plan.versions[chosen - 1]
    sequence = _preview(review, selection, parent, plan.sequence)
    if not _confirm("approve"):
        return _cancel()
    review.decide(selection, parent, approve=True, expected_sequence=sequence)
    result = host.run_authored_draft(
        selection,
        parent,
        arguments.brief,
        authored_draft_input(review.read(selection, parent)),
        screen_scores=dict.fromkeys(HAZARDS, 0.01),
        support_verdict="supports",
        expected_sequence=review.sequence(selection),
    )
    if result.version is None:
        _emit({"status": "draft_refused", "codes": result.dropped_codes, "exported": False})
        return 0
    sequence = _preview(review, selection, result.version, result.sequence)
    if not _confirm("approve"):
        return _cancel()
    review.decide(selection, result.version, approve=True, expected_sequence=sequence)
    sequence = review.sequence(selection)
    key = "terminal-" + uuid4().hex
    # Print recovery metadata before copying files; a failed local write can be replayed.
    _emit({"selection": selection.model_dump(mode="json"), "receipt_key": key})
    if not _confirm("export"):
        return _cancel()
    bundle = review.export(
        selection, idempotency_key=key, items=(result.version,), expected_sequence=sequence
    )
    _download(bundle, arguments.output_dir)
    return 0


def receipt_command(arguments):
    host = local_host(arguments.database, arguments.call_database, arguments.namespace)
    selection = Selection(dataset_id=arguments.dataset_id, snapshot_id=arguments.snapshot_id)
    bundle = host.review.download_receipt(selection, arguments.key)
    _download(bundle, arguments.output_dir)
    return 0


def _cancel():
    _emit({"status": "cancelled", "exported": False})
    return 0
