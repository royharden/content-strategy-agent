"""Public display example arithmetic/status controls, independent of private evaluation data."""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
render_fixture = runpy.run_path(str(ROOT / "scripts/export_static_fixture.py"))["render_fixture"]


def fixture():
    return json.loads(render_fixture((ROOT / "fixtures/ui/static-example.csv").read_bytes()))


def test_static_example_uses_ratio_of_sums_and_exact_eligible_counts():
    """what_bug_this_catches: a mean of post rates or date-only rows counted as timed evidence."""
    value = fixture()
    rows = {row["metric"]["metric_id"]: row for row in value["rows"]}
    # This example has one format; its six-row rate covers the complete source.
    overall = rows["er.linkedin.format.text"]
    assert overall["numerator"] == "115" and overall["denominator"] == "1500"
    assert overall["metric"]["value"] == "0.07666667"
    assert overall["metric"]["sample_size"] == 6 and overall["metric"]["status"] == "ok"
    assert value["platforms"][0]["missing_time_rows"] == 2
    hour = rows["er.linkedin.hour.9"]
    assert hour["metric"]["sample_size"] == 4
    assert hour["metric"]["status"] == "insufficient_data"
    trend = rows["trend.linkedin.overall.4w"]["metric"]
    assert trend["value"] is None and trend["status"] == "unavailable"


def test_public_example_bytes_cannot_silently_drift_from_production_projection():
    """what_bug_this_catches: static values diverge from the checked source/config computation."""
    source = (ROOT / "fixtures/ui/static-example.csv").read_bytes()
    assert (ROOT / "web/static-fixture.json").read_bytes() == render_fixture(source).encode()
    value = fixture()
    assert value["authority"] == "display_only_no_approvals_receipts_or_persistence"
    assert value["mode"] == "authored_synthetic_static_fixture"
    assert not {"approval", "receipt", "actor", "csrf", "cookie"}.intersection(value)
