import json
import subprocess
import sys
from pathlib import Path

import pytest

from content_strategy.shared.grounded.audit import GateError
from content_strategy.shared.grounded.validation import validate

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "conformance/grounded-runtime-v1.vectors.json"
    ).read_text(encoding="utf-8")
)


def test_runtime_schema_generator_matches_and_does_not_replace_wp01_contract(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "conformance/export_runtime_schemas.py"), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    runtime = json.loads((root / "conformance/grounded-runtime-v1.schema.json").read_text())
    structural = json.loads((root / "schemas/grounded-v1.json").read_text())
    assert runtime["structural_only"] is True and len(runtime["models"]) == 7
    assert len(structural["models"]) == 13
    copied = tmp_path / "export_runtime_schemas.py"
    copied.write_text((root / "conformance/export_runtime_schemas.py").read_text())
    (tmp_path / "grounded-runtime-v1.schema.json").write_text("{}")
    bad = subprocess.run(
        [sys.executable, str(copied), "--check"], capture_output=True, text=True, timeout=20
    )
    assert bad.returncode == 1


@pytest.mark.parametrize("case", VECTORS["validator_cases"], ids=lambda c: c["name"])
def test_language_neutral_validator_vectors(harness, case):
    h = harness()
    report = validate(h.content(text=case["text"]), h.resolver, h.policy).report
    assert sorted(f.code for f in report.failures) == sorted(case["codes"])


@pytest.mark.parametrize("case", VECTORS["state_cases"], ids=lambda c: c["name"])
def test_language_neutral_state_vectors(harness, case):
    h = harness()
    h.activate()
    rec = h.content()
    draft = h.content(kind="draft", item_id="draft", parent_id="rec", parent_revision=1)
    actions = {
        "save_rec": lambda: h.save(rec),
        "approve_rec": lambda: h.approve(rec),
        "reject_rec": lambda: h.store.decide(
            "rec", 1, approve=False, actor_label="user", expected_sequence=h.store.sequence
        ),
        "save_draft": lambda: h.save(draft),
        "approve_draft": lambda: h.approve(draft),
    }
    if case["denied"]:
        with pytest.raises(GateError, match=case["denied"]):
            for action in case["actions"]:
                actions[action]()
    else:
        for action in case["actions"]:
            actions[action]()
    target = "draft" if "approve_draft" in case["actions"] else "rec"
    assert h.store.state(target, 1) == case["state"]


@pytest.mark.parametrize("case", VECTORS["export_cases"], ids=lambda c: c["name"])
def test_language_neutral_export_vectors(harness, case):
    h = harness()
    h.activate()
    rec = h.content()
    h.save(rec)
    h.approve(rec)
    draft = h.content(kind="draft", item_id="draft", parent_id="rec", parent_revision=1)
    h.save(draft)
    if case["approve_draft"]:
        h.approve(draft)
    request = h.request(draft)
    if case["denied"]:
        with pytest.raises(GateError, match=case["denied"]):
            h.store.export(request)
    else:
        bundle = h.store.export(request)
        replay = h.store.replay(request)
        assert bundle.markdown and bundle.csv and replay.receipt == bundle.receipt
