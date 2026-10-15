"""Actual terminal process/restart control with scripted synthetic decisions, not Human evidence."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_actual_module_entrypoint_review_then_fresh_process_receipt(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    environment = {
        "PYTHONPATH": str(repo / "src"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if name in os.environ:
            environment[name] = os.environ[name]
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
        "native-terminal",
        "--output-dir",
        str(tmp_path / "downloads"),
    ]
    result = subprocess.run(
        [sys.executable, "-m", "content_strategy", "review", *common, "--file", str(source)],
        cwd=tmp_path,
        env=environment,
        input="activate\n1\napprove\napprove\nexport\n",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    records = []
    for line in result.stdout.splitlines():
        offset = line.find("{")
        if offset >= 0:
            records.append(json.loads(line[offset:]))
    exported = records[-1]
    selection = records[0]["selection"]
    assert records[0]["quality_measurement"] is False
    assert len(exported["receipt"]["approval_event_ids"]) == 2
    replay = subprocess.run(
        [
            sys.executable,
            "-m",
            "content_strategy",
            "receipt",
            *common,
            "--dataset-id",
            selection["dataset_id"],
            "--snapshot-id",
            selection["snapshot_id"],
            "--key",
            exported["receipt"]["idempotency_key"],
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert replay.returncode == 0, replay.stderr
    recovered = json.loads(replay.stdout)
    assert recovered["historical_replay"] is True
    assert recovered["receipt"] == exported["receipt"]
    for kind in ("markdown", "csv"):
        assert Path(recovered[kind]).read_bytes() == Path(exported[kind]).read_bytes()
