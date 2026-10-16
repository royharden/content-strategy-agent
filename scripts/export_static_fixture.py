"""Build the public read-only UI example from production arithmetic, without storage or AI."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from content_strategy.ingest import ingest_csv
from content_strategy.metrics import compute_metrics

ROOT = Path(__file__).resolve().parents[1]


def render_fixture(payload: bytes) -> str:
    dataset = ingest_csv(payload)
    report = compute_metrics(dataset, created_at=datetime(2026, 10, 1, tzinfo=UTC))
    document = {
        "edition": "read-only-ui-example.v1",
        "mode": "authored_synthetic_static_fixture",
        "authority": "display_only_no_approvals_receipts_or_persistence",
        "source": {
            "path": "fixtures/ui/static-example.csv",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "rows": len(dataset.rows),
            "dataset_fingerprint": dataset.fingerprint,
        },
        "snapshot_id": report.snapshot.snapshot_id,
        "platforms": [
            {
                "platform": summary.platform,
                "rows": summary.rows,
                "missing_time_rows": summary.missing_time_rows,
            }
            for summary in report.platforms
        ],
        "rows": [
            {
                "metric": row.metric.model_dump(mode="json"),
                "family": row.family,
                "numerator": str(row.numerator),
                "denominator": str(row.denominator),
            }
            for row in report.computations
        ],
    }
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render_fixture((ROOT / "fixtures/ui/static-example.csv").read_bytes()).encode()
    target = ROOT / "web/static-fixture.json"
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            parser.exit(1, "Static example differs from production arithmetic/source bytes\n")
    else:
        target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
