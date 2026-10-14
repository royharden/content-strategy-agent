import subprocess
import sys
from pathlib import Path

import pytest

from content_strategy.shared.grounded.audit import GateError


@pytest.mark.parametrize(("stage", "committed"), [("before_commit", False), ("after_commit", True)])
def test_real_process_exit_before_or_after_commit(harness, tmp_path, stage, committed):
    h = harness()
    _, draft = h.journey()
    request = h.request(draft)
    request_file = tmp_path / "request.json"
    request_file.write_text(request.model_dump_json())
    program = r"""
import os, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from content_strategy.shared.grounded.audit import AuditStore, ExportRequest
from content_strategy.shared.grounded.validation import Assessment, Policy
from content_strategy.shared.grounded.models import Metric


class Resolver:
    def current_generation(self, scope):
        return "a" * 64 if scope == "corpus" else None

    def resolve(self, key):
        return Metric(
            metric_id="fact",
            snapshot_id="a" * 64,
            scope="corpus",
            definition="Exact synthetic evidence",
            value="0.125",
            unit="ratio",
            sample_size=5,
            computed_by="oracle.v1",
            status="ok",
        )


def assess(checked, policy):
    return Assessment(
        content_hash=checked.content.item.content_hash,
        evidence_hash=checked.evidence_hash,
        policy_hash=policy.digest,
        screen_edition=policy.screen_edition,
        screen_status="pass",
        semantic_status="supports",
    )


def fault(stage):
    if stage == sys.argv[4]:
        os._exit(73)


store = AuditStore(
    sys.argv[2],
    namespace="test",
    policy=Policy(screen_edition="injected-fixture.v1"),
    resolver=Resolver(),
    authorize=lambda *args: True,
    assess=assess,
    fault=fault,
)
store.export(ExportRequest.model_validate_json(Path(sys.argv[3]).read_text()))
raise AssertionError("fault did not execute")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(Path(__file__).resolve().parents[2] / "src"),
            str(tmp_path / "authority.sqlite3"),
            str(request_file),
            stage,
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 73, result.stderr
    if committed:
        result = h.store.replay(request)
        assert result.markdown and result.csv and result.historical_replay
        assert h.store.state("draft", 1) == "exported"
    else:
        with pytest.raises(GateError, match="unknown_receipt"):
            h.store.replay(request)
        assert h.store.state("draft", 1) == "approved"
        assert h.store.export(request).receipt
