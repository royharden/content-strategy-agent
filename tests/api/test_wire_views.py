"""Pure browser contract checks; no FastAPI factory import or HTTP execution."""

import base64
import json

import pytest

from content_strategy.api.views import report_view
from content_strategy.api.wire import ExportInput, ImportInput, VersionInput, parse_input
from content_strategy.metrics.grounding import MetricsResolver
from content_strategy.pipeline.assembly import recommendation_content
from content_strategy.runtime.examples import authored_plan_inputs, demo_csv
from content_strategy.shared.grounded.validation import Policy, validate
from content_strategy.storage import SourceStore


def version_frame():
    return {
        "selection": {"dataset_id": "s9-dataset-" + "a" * 32, "snapshot_id": "b" * 64},
        "expected_sequence": 1,
        "version": {
            "schema_version": 1,
            "item_id": "rec",
            "revision": 1,
            "content_hash": "c" * 64,
            "evidence_generation": "b" * 64,
        },
    }


def test_import_preserves_original_bom_crlf_bytes_and_clock():
    raw = b"\xef\xbb\xbf" + demo_csv()
    value = parse_input(
        json.dumps({"csv_base64": base64.b64encode(raw).decode(), "clock": "fixed-utc"}).encode(),
        ImportInput,
    )
    assert value.csv_bytes() == raw and value.clock == "fixed-utc"


@pytest.mark.parametrize("value", ["not base64", "YWJj\n", "🔥"])
def test_invalid_base64_is_closed_refusal(value):
    with pytest.raises(ValueError, match="invalid_csv_encoding"):
        ImportInput(csv_base64=value).csv_bytes()


@pytest.mark.parametrize(
    "field",
    [
        "actor_label",
        "namespace",
        "policy",
        "screen_scores",
        "candidate",
        "assessment",
        "proof",
        "database",
    ],
)
def test_client_cannot_supply_trusted_host_fields(field):
    document = version_frame() | {field: "client supplied"}
    with pytest.raises(ValueError, match="invalid_request"):
        parse_input(json.dumps(document).encode(), VersionInput)


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"null",
        b'{"x":1,"x":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b"\xff",
    ],
)
def test_nonobject_duplicate_nonfinite_and_nonutf8_inputs_refused(raw):
    with pytest.raises(ValueError, match="invalid_request"):
        parse_input(raw, VersionInput)


@pytest.mark.parametrize("sequence", [True, "1", 1.0, -1])
def test_strict_sequence_cannot_be_coerced(sequence):
    document = version_frame() | {"expected_sequence": sequence}
    with pytest.raises(ValueError, match="invalid_request"):
        parse_input(json.dumps(document).encode(), VersionInput)


def test_actual_json_export_array_becomes_exact_strict_tuple():
    document = version_frame()
    document["items"] = [document.pop("version")]
    document["idempotency_key"] = "download-once"
    value = parse_input(json.dumps(document).encode(), ExportInput)
    assert type(value.items) is tuple and value.items[0].revision == 1


def test_exact_large_arithmetic_is_string_not_browser_float_and_no_raw_post_text(tmp_path):
    sentinel = "PRIVATE_POST_BODY_MUST_NOT_BE_IN_REPORT"
    raw = (
        "post_id,date,platform,text,impressions,likes,comments,shares\n"
        + "".join(f"p{i},2026-01-01,linkedin,{sentinel},10,{'9' * 128},0,0\n" for i in range(5))
    ).encode()
    with SourceStore(tmp_path / "source.sqlite3", namespace="local") as store:
        retained = store.import_csv(raw)
    view = report_view(retained)
    text = json.dumps(view)
    assert sentinel not in text
    assert view["selection"]["snapshot_id"] == retained.report.snapshot.snapshot_id
    assert all(
        type(row["numerator"]) is str and type(row["denominator"]) is str for row in view["rows"]
    )
    assert any(len(row["numerator"]) >= 128 for row in view["rows"])
    assert all(
        row["metric"]["value"] is None or isinstance(row["metric"]["value"], str)
        for row in view["rows"]
    )
    assert any(row["metric"]["status"] == "unavailable" for row in view["rows"])


def test_authored_demo_plan_uses_only_actual_citable_metrics_and_does_not_run_a_model(tmp_path):
    with SourceStore(tmp_path / "source.sqlite3", namespace="local") as store:
        retained = store.import_csv(demo_csv())
    snapshot = retained.report.snapshot
    candidates, verdicts = authored_plan_inputs(snapshot)
    assert len(candidates) == 5 and len(verdicts) == 5
    for candidate in candidates:
        checked = validate(
            recommendation_content(candidate, snapshot.snapshot_id),
            MetricsResolver(snapshot),
            Policy(screen_edition="synthetic-test"),
        )
        assert not checked.report.failures
    view = report_view(retained)
    assert {row["platform"] for row in view["platforms"]} == {"x", "linkedin"}
    assert all(row["rows"] == 12 for row in view["platforms"])
