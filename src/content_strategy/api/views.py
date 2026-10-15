"""Browser projections retain exact values and distinguish n from diagnostic counts."""

import base64
from dataclasses import asdict

from ..shared.grounded.audit import Bundle
from ..storage import Retained


def selection_view(retained: Retained):
    return {"dataset_id": retained.dataset_id, "snapshot_id": retained.report.snapshot.snapshot_id}


def report_view(retained: Retained):
    report = retained.report
    return {
        "selection": selection_view(retained),
        "dataset_fingerprint": retained.dataset.fingerprint,
        "original_byte_sha256": retained.dataset.original_sha256,
        "report_sha256": retained.report_sha256,
        "identity": report.snapshot.identity.model_dump(mode="json"),
        "created_at": report.snapshot.created_at.isoformat(),
        "platforms": [asdict(summary) for summary in report.platforms],
        "rows": [
            {
                "metric": row.metric.model_dump(mode="json"),
                "family": row.family,
                "dimension": row.dimension,
                "key": row.key,
                "numerator": str(row.numerator),
                "denominator": str(row.denominator),
                "eligible_ids": list(row.eligible_ids),
                "excluded_ids": list(row.excluded_ids),
                "windows": [
                    {
                        "start_ordinal": window.start_ordinal,
                        "end_ordinal": window.end_ordinal,
                        "eligible_ids": list(window.eligible_ids),
                        "numerator": str(window.numerator),
                        "denominator": str(window.denominator),
                    }
                    for window in row.windows
                ],
            }
            for row in report.computations
        ],
    }


def bundle_view(bundle: Bundle):
    return {
        "receipt": bundle.receipt.model_dump(mode="json"),
        "historical_replay": bundle.historical_replay,
        "markdown_base64": base64.b64encode(bundle.markdown).decode("ascii"),
        "csv_base64": base64.b64encode(bundle.csv).decode("ascii"),
    }
