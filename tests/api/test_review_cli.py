"""Tiny owned synthetic controls for explicit terminal decisions and durable receipts."""

import json
import socket
import sqlite3
from pathlib import Path

import pytest

from content_strategy.api.service import Selection
from content_strategy.cli import main
from content_strategy.runtime.local import local_host


@pytest.fixture
def command(tmp_path):
    source = tmp_path / "tiny.csv"
    source.write_bytes(
        b"post_id,date,platform,text,impressions,likes,comments,shares\n"
        + b"".join(f"p{i},2026-10-01,linkedin,synthetic,100,5,2,1\n".encode() for i in range(6))
    )
    common = [
        "--database",
        str(tmp_path / "review.sqlite3"),
        "--call-database",
        str(tmp_path / "calls.sqlite3"),
        "--namespace",
        "terminal-test",
        "--output-dir",
        str(tmp_path / "downloads"),
    ]
    return ["review", *common, "--file", str(source)], common


def answers(monkeypatch, values):
    values = iter(values)

    def respond(_prompt):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", respond)


def records(capsys):
    return [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]


def test_terminal_two_decisions_export_and_real_restart_receipt(command, monkeypatch, capsys):
    """Catches CLI bypasses or regenerated exports instead of committed-byte replay."""

    def no_socket(*args, **kwargs):
        raise AssertionError("offline terminal journey attempted a socket")

    monkeypatch.setattr(socket, "socket", no_socket)
    arguments, common = command
    answers(monkeypatch, ["activate", "1", "approve", "approve", "export"])
    assert main(arguments) == 0
    rows = records(capsys)
    exported = rows[-1]
    selection = next(row["selection"] for row in rows if "selection" in row)
    assert rows[0]["execution_origin"] == "authored_synthetic_mock"
    assert rows[0]["model_calls"] is False and rows[0]["quality_measurement"] is False
    assert len(exported["receipt"]["approval_event_ids"]) == 2
    original = {kind: Path(exported[kind]).read_bytes() for kind in ("markdown", "csv")}
    assert all(original.values())
    key = exported["receipt"]["idempotency_key"]
    assert (
        main(
            [
                "receipt",
                *common,
                "--dataset-id",
                selection["dataset_id"],
                "--snapshot-id",
                selection["snapshot_id"],
                "--key",
                key,
            ]
        )
        == 0
    )
    replay = records(capsys)[-1]
    assert replay["historical_replay"] is True
    assert replay["markdown"] != exported["markdown"]
    assert {kind: Path(replay[kind]).read_bytes() for kind in original} == original


@pytest.mark.parametrize(
    "inputs",
    [
        [],
        [""],
        ["activate"],
        ["activate", "0"],
        ["activate", "1", "no"],
        ["activate", "1", "approve"],
        ["activate", "1", "approve", "approve"],
        ["activate", "1", "approve", "approve", "no"],
    ],
)
def test_decline_or_eof_at_any_confirmation_never_exports(command, monkeypatch, capsys, inputs):
    """Catches default-yes behavior and EOF interpreted as an approval/export."""
    arguments, _ = command
    answers(monkeypatch, inputs)
    assert main(arguments) == 0
    assert records(capsys)[-1] == {"status": "cancelled", "exported": False}
    database = Path(arguments[arguments.index("--database") + 1])
    with sqlite3.connect(database) as db:
        assert not db.execute("SELECT 1 FROM grounded_receipts").fetchall()
    assert not Path(arguments[arguments.index("--output-dir") + 1]).exists()


def test_invalid_csv_has_no_review_ledger_or_download_side_effect(command, capsys):
    arguments, _ = command
    Path(arguments[-1]).write_bytes(b"post_id,date\nbad\n")
    assert main(arguments) == 2
    assert records(capsys)[-1]["error"] == "invalid_csv"
    for option in ("--database", "--call-database", "--output-dir"):
        assert not Path(arguments[arguments.index(option) + 1]).exists()


@pytest.mark.parametrize("defect", ["value", "citation"])
def test_invalid_authored_citation_cannot_reach_approval_or_export(
    command, monkeypatch, capsys, defect
):
    """Catches a terminal adapter bypassing the existing exact citation validator."""
    from content_strategy import review_cli

    original = review_cli.authored_plan_inputs

    def invalid(snapshot):
        candidates, verdicts = original(snapshot)
        bad = []
        for candidate in candidates:
            citation = candidate.citations[0].model_copy(
                update=({"quoted_value": "999"} if defect == "value" else {"metric_id": "missing"})
            )
            bad.append(candidate.model_copy(update={"citations": (citation,)}))
        return tuple(bad), verdicts

    monkeypatch.setattr(review_cli, "authored_plan_inputs", invalid)
    arguments, _ = command
    answers(monkeypatch, ["activate", "1", "approve", "approve", "export"])
    result = main(arguments)
    rows = records(capsys)
    assert result == 2 or rows[-1].get("status") == "no_valid_recommendations"
    assert not Path(arguments[arguments.index("--output-dir") + 1]).exists()


@pytest.mark.parametrize("change", ["revoke", "context"])
def test_change_after_last_preview_blocks_export(command, monkeypatch, capsys, change):
    """Catches stale observed approvals being treated as an export lease."""
    from content_strategy import review_cli

    arguments, _ = command
    real_host = review_cli.local_host
    active = []

    def capture(*args):
        host = real_host(*args)
        active.append(host)
        return host

    monkeypatch.setattr(review_cli, "local_host", capture)
    inputs = iter(["activate", "1", "approve", "approve", "export"])

    def respond(prompt):
        if prompt.startswith("Type export"):
            review = active[0].review
            with sqlite3.connect(review.database) as db:
                row = db.execute("SELECT dataset_id,snapshot_id FROM s9_reports LIMIT 1").fetchone()
            selection = Selection(dataset_id=row[0], snapshot_id=row[1])
            if change == "revoke":
                draft = next(
                    row.version for row in review.history(selection) if row.kind == "draft"
                )
                review.revoke(selection, draft, expected_sequence=review.sequence(selection))
            else:
                retained = review.import_csv(
                    b"post_id,date,platform,text,impressions,likes,comments,shares\n"
                    b"new,2026-10-02,linkedin,changed,100,5,2,1\n"
                )
                other = Selection(
                    dataset_id=retained.dataset_id, snapshot_id=retained.report.snapshot.snapshot_id
                )
                review.activate(other, expected_sequence=review.sequence(selection))
        return next(inputs)

    monkeypatch.setattr("builtins.input", respond)
    assert main(arguments) == 2
    assert records(capsys)[-1]["error"] == "local_analysis_unavailable"
    assert not Path(arguments[arguments.index("--output-dir") + 1]).exists()


def test_local_host_refuses_shared_review_and_call_database(tmp_path):
    with pytest.raises(ValueError, match="trusted_host_binding_required"):
        local_host(tmp_path / "same.sqlite3", tmp_path / "same.sqlite3", "test")
