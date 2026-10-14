import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_actual_renamed_corpus_and_queue_runtime_consumers(tmp_path):
    package = tmp_path / "renamed_plugin"
    package.mkdir()
    (package / "__init__.py").write_text("")
    shutil.copytree(REPO / "src/content_strategy/shared/grounded", package / "evidence")
    program = r"""
import sys


class BlockOwner:
    def find_spec(self, fullname, path=None, target=None):
        if (
            fullname == "content_strategy"
            or fullname.startswith("content_strategy.")
            or fullname == "tests"
            or fullname.startswith("tests.")
        ):
            raise ImportError("owner/test package unavailable")


sys.meta_path.insert(0, BlockOwner())
sys.path.insert(0, sys.argv[1])
from renamed_plugin.evidence.models import EvidenceKey, Metric, MetricCitation
from renamed_plugin.evidence.validation import (
    Assessment,
    PassageEvidence,
    PassageCitation,
    Policy,
    seal_content,
    validate,
)
from renamed_plugin.evidence.audit import AuditStore, ExportRequest, GateError, _version

generation = "a" * 64
key = EvidenceKey(generation=generation, evidence_id="section", scope="rfp")


class Corpus:
    def current_generation(self, scope):
        return generation if scope == "rfp" else None

    def resolve(self, requested):
        return (
            PassageEvidence(key=key, excerpt="Delivery within 30 days.", status="ok")
            if requested == key
            else None
        )


corpus = Corpus()
policy = Policy(screen_edition="explicit-fixture")


def content(quote):
    return seal_content(
        item_id="proposal",
        revision=1,
        kind="recommendation",
        scope="rfp",
        snapshot_id=generation,
        text="Requirement: {{cite:section}}",
        citations=(),
        passages=(PassageCitation(key=key, quoted_text=quote),),
    )


good = content("Delivery within 30 days.")
checked = validate(good, corpus, policy)
assert checked.report.structural_status == "valid" and "30 days" in checked.rendered
assert (
    validate(content("Delivery within 20 days."), corpus, policy).report.structural_status
    == "invalid"
)
assert good.__class__.__module__.startswith("renamed_plugin.")


class Queue:
    def current_generation(self, scope):
        return generation if scope == "gateway" else None

    def resolve(self, key):
        return (
            Metric(
                metric_id="units",
                snapshot_id=generation,
                scope="gateway",
                definition="Reviewed quota",
                value="7",
                unit="units",
                sample_size=5,
                computed_by="queue.fixture",
                status="ok",
            )
            if key.generation == generation
            and key.scope == "gateway"
            and key.evidence_id == "units"
            else None
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


store = AuditStore(
    sys.argv[1] + "/queue.sqlite3",
    namespace="gateway",
    policy=policy,
    resolver=Queue(),
    authorize=lambda actor, action, content: actor == "reviewer",
    assess=assess,
)
store.activate_context(generation, expected_sequence=0)
citation = MetricCitation(
    snapshot_id=generation, metric_id="units", scope="gateway", quoted_value="7", unit="units"
)
rec = seal_content(
    item_id="request",
    revision=1,
    kind="recommendation",
    scope="gateway",
    snapshot_id=generation,
    text="Reviewed {{cite:units}}",
    citations=(citation,),
)
store.save(rec, actor_label="reviewer", expected_revision=0, expected_sequence=store.sequence)
store.decide("request", 1, approve=True, actor_label="reviewer", expected_sequence=store.sequence)
draft = seal_content(
    item_id="response",
    revision=1,
    kind="draft",
    scope="gateway",
    snapshot_id=generation,
    text="Allowed {{cite:units}}",
    citations=(citation,),
    parent_id="request",
    parent_revision=1,
)
store.save(draft, actor_label="reviewer", expected_revision=0, expected_sequence=store.sequence)
request = ExportRequest(
    idempotency_key="bundle",
    actor_label="reviewer",
    generation=generation,
    policy_hash=policy.digest,
    expected_sequence=store.sequence,
    items=(_version(draft),),
)
try:
    store.export(request)
except GateError:
    pass
else:
    raise AssertionError("unapproved response accepted")
store.decide("response", 1, approve=True, actor_label="reviewer", expected_sequence=store.sequence)
request = ExportRequest(**(request.model_dump() | {"expected_sequence": store.sequence}))
bundle = store.export(request)
assert bundle.markdown and bundle.csv and len(bundle.receipt.approval_event_ids) == 2
assert store.replay(request).receipt == bundle.receipt
store.close()
assert not any(
    name == "content_strategy" or name.startswith("content_strategy.") for name in sys.modules
)
print(
    "PASS: detached M3 exact passage positive/wrong-quote negative; "
    "M8 two approvals/export/refusal/replay"
)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "PASS: detached M3" in result.stdout
