"""Explicit local analysis commands; no provider, activation or approval effects."""

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .ingest import MAX_BYTES, IngestError, ingest_csv
from .metrics import AnalysisConfig
from .storage import SourceStore, StorageError


def _summary(retained):
    return {
        "dataset_id": retained.dataset_id,
        "source_fingerprint": retained.dataset.fingerprint,
        "original_sha256": retained.dataset.original_sha256,
        "snapshot_id": retained.report.snapshot.snapshot_id,
        "report_sha256": retained.report_sha256,
        "rows": len(retained.dataset.rows),
        "retained_only": True,
        "activation_or_approval": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Content Strategy Agent: explicit local analysis.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--status-json", action="store_true")
    commands = parser.add_subparsers(dest="command")
    for name in ("import-csv", "report"):
        command = commands.add_parser(name)
        command.add_argument("--database", required=True, type=Path)
        command.add_argument("--namespace", required=True)
        if name == "import-csv":
            command.add_argument("--file", required=True, type=Path)
            command.add_argument(
                "--clock", choices=("posted-local", "fixed-utc"), default="posted-local"
            )
        else:
            command.add_argument("--dataset-id", required=True)
            command.add_argument("--snapshot-id", required=True)
    arguments = parser.parse_args(argv)
    if arguments.status_json:
        if arguments.command:
            parser.error("--status-json cannot be combined with a storage command")
        print(
            json.dumps(
                {
                    "stage": "local-components",
                    "version": __version__,
                    "implemented_workflows": ["local_csv_analysis"],
                    "implemented_components": [
                        "grounded_structural_models",
                        "canonical_identity",
                        "csv_ingest",
                        "deterministic_metrics",
                        "grounding_validation",
                        "sqlite_approval_receipts",
                        "staged_pipeline_ports",
                        "baseline_tagging",
                        "linkedin_utf16_limits",
                        "published_offline_ledger_provider",
                        "published_rules_screen",
                        "local_source_reports",
                    ],
                    "schema_validation_is_authorization": False,
                    "provider_calls": False,
                    "approval_export_available": False,
                    "local_module_approval_export": True,
                    "x_drafts_supported": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if not arguments.command:
        parser.print_help()
        return 0
    try:
        if arguments.command == "import-csv":
            with arguments.file.open("rb") as stream:
                payload = stream.read(MAX_BYTES + 1)
            ingest_csv(payload)  # Validate before opening/creating any database.
            with SourceStore(arguments.database, namespace=arguments.namespace) as store:
                retained = store.import_csv(payload, config=AnalysisConfig(arguments.clock))
                output = _summary(retained)
        else:
            if not arguments.database.is_file():
                raise StorageError("database_not_found")
            with SourceStore(arguments.database, namespace=arguments.namespace) as store:
                retained = store.load(arguments.dataset_id, arguments.snapshot_id)
                output = _summary(retained) | {
                    "snapshot": retained.report.snapshot.model_dump(mode="json"),
                    "platforms": [asdict(value) for value in retained.report.platforms],
                }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except IngestError as error:
        print(json.dumps({"error": "invalid_csv", "issues": [asdict(x) for x in error.issues]}))
    except StorageError as error:
        print(json.dumps({"error": str(error)}))
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({"error": "local_analysis_unavailable"}))
    return 2
