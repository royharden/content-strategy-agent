"""Explicit local source/report retention; retained reports convey no current approval."""

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ..ingest import Dataset, ingest_csv
from ..metrics import AnalysisConfig, AnalyticsReport, compute_metrics
from ..shared.grounded.audit import AuditStore, GateError
from ..shared.grounded.models import TagProvenance
from ..shared.grounded.validation import Policy

MAX_REPORT_BYTES = 32 * 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS s9_sources(
 namespace TEXT NOT NULL,dataset_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
 original_sha256 TEXT NOT NULL,raw_csv BLOB NOT NULL,
 PRIMARY KEY(namespace,dataset_id),UNIQUE(namespace,fingerprint,original_sha256));
CREATE TABLE IF NOT EXISTS s9_reports(
 namespace TEXT NOT NULL,dataset_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,
 report_sha256 TEXT NOT NULL,report BLOB NOT NULL,config TEXT NOT NULL,tags TEXT,
 PRIMARY KEY(namespace,dataset_id,snapshot_id),
 FOREIGN KEY(namespace,dataset_id) REFERENCES s9_sources(namespace,dataset_id));
"""
for _table in ("s9_sources", "s9_reports"):
    for _action in ("UPDATE", "DELETE"):
        SCHEMA += (
            f"CREATE TRIGGER IF NOT EXISTS {_table}_{_action.lower()} BEFORE {_action} "
            f"ON {_table} BEGIN SELECT RAISE(ABORT,'s9_append_only'); END;\n"
        )
    _key = (
        "dataset_id=NEW.dataset_id AND snapshot_id=NEW.snapshot_id"
        if _table == "s9_reports"
        else "(dataset_id=NEW.dataset_id OR (fingerprint=NEW.fingerprint "
        "AND original_sha256=NEW.original_sha256))"
    )
    SCHEMA += (
        f"CREATE TRIGGER IF NOT EXISTS {_table}_replace BEFORE INSERT ON {_table} "
        f"WHEN EXISTS(SELECT 1 FROM {_table} WHERE namespace=NEW.namespace "
        f"AND {_key}) "
        "BEGIN SELECT RAISE(ABORT,'s9_append_only'); END;\n"
    )


class StorageError(ValueError):
    """Closed local storage errors; never interpolate source text or database paths."""


class _NoEvidence:
    def current_generation(self, scope):
        return None

    def resolve(self, key):
        return None


def _no_assessment(*args):
    raise GateError("storage_has_no_review_authority")


def _json(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _report_bytes(report: AnalyticsReport) -> bytes:
    computations = []
    for row in report.computations:
        value = {key: val for key, val in asdict(row).items() if key != "metric"}
        value["metric"] = row.metric.model_dump(mode="json")
        computations.append(value)
    return _json(
        {
            "edition": "s9-retained-report.v1",
            "snapshot": report.snapshot.model_dump(mode="json"),
            "computations": computations,
            "platforms": [asdict(row) for row in report.platforms],
        }
    )


@dataclass(frozen=True)
class Retained:
    dataset_id: str
    dataset: Dataset
    report: AnalyticsReport
    report_sha256: str


class SourceStore:
    """Trusted host supplies the path/namespace; API authentication belongs outside this class.

    No active-source pointer exists here. AuditStore's context and approval checks remain
    authoritative. Callers select exact historical dataset/snapshot IDs explicitly.
    """

    def __init__(self, database: str | Path, *, namespace: str):
        if type(namespace) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace):
            raise StorageError("invalid_namespace")
        self.namespace = namespace
        # Apply and verify the generic migration through its actual public constructor,
        # unmodified. Bootstrap callbacks cannot authorize or assess any content.
        bootstrap = AuditStore(
            database,
            namespace=namespace,
            policy=Policy(screen_edition="storage-disabled"),
            resolver=_NoEvidence(),
            authorize=lambda *args: False,
            assess=_no_assessment,
        )
        bootstrap.close()
        self.connection = sqlite3.connect(database, isolation_level=None, timeout=5)
        self.connection.execute("PRAGMA foreign_keys=ON")
        reference = sqlite3.connect(":memory:")
        reference.executescript(SCHEMA)
        self.expected_schema = self._schema(reference)
        reference.close()
        existing = self._schema(self.connection)
        if existing and existing != self.expected_schema:
            self.connection.close()
            raise StorageError("storage_schema_tamper")
        self.connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")

    @staticmethod
    def _schema(connection):
        return tuple(
            connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name GLOB 's9_*' "
                "AND sql IS NOT NULL ORDER BY type,name"
            )
        )

    @contextmanager
    def _transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self._schema(self.connection) != self.expected_schema:
                raise StorageError("storage_schema_tamper")
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def import_csv(
        self,
        payload: bytes,
        *,
        config: AnalysisConfig | None = None,
        tag_provenance: tuple[TagProvenance, ...] | None = None,
        created_at: datetime | None = None,
    ) -> Retained:
        # All input, tagging, computation and complete report caps validate before writes.
        dataset = ingest_csv(payload)
        config = config or AnalysisConfig()
        report = compute_metrics(
            dataset, config, tag_provenance=tag_provenance, created_at=created_at
        )
        raw = _report_bytes(report)
        if len(raw) > MAX_REPORT_BYTES:
            raise StorageError("report_byte_limit")
        config_json = _json(config.document()).decode("utf-8")
        tags_json = (
            None
            if tag_provenance is None
            else _json([tag.model_dump(mode="json") for tag in tag_provenance]).decode("utf-8")
        )
        with self._transaction():
            existing = self.connection.execute(
                "SELECT dataset_id FROM s9_sources WHERE namespace=? AND fingerprint=? "
                "AND original_sha256=?",
                (self.namespace, dataset.fingerprint, dataset.original_sha256),
            ).fetchone()
            dataset_id = existing[0] if existing else "s9-dataset-" + uuid.uuid4().hex
            if not existing:
                self.connection.execute(
                    "INSERT INTO s9_sources VALUES(?,?,?,?,?)",
                    (
                        self.namespace,
                        dataset_id,
                        dataset.fingerprint,
                        dataset.original_sha256,
                        payload,
                    ),
                )
            previous = self.connection.execute(
                "SELECT snapshot_id FROM s9_reports WHERE namespace=? AND dataset_id=? "
                "AND snapshot_id=?",
                (self.namespace, dataset_id, report.snapshot.snapshot_id),
            ).fetchone()
            if previous is None:
                self.connection.execute(
                    "INSERT INTO s9_reports VALUES(?,?,?,?,?,?,?)",
                    (
                        self.namespace,
                        dataset_id,
                        report.snapshot.snapshot_id,
                        hashlib.sha256(raw).hexdigest(),
                        raw,
                        config_json,
                        tags_json,
                    ),
                )
            # A duplicate retains the first exact timestamp/bytes. Revalidate stored source,
            # configuration and all derived values rather than trusting a prior ID alone.
            return self._load(dataset_id, report.snapshot.snapshot_id)

    def load(self, dataset_id: str, snapshot_id: str) -> Retained:
        if type(dataset_id) is not str or not re.fullmatch(r"s9-dataset-[0-9a-f]{32}", dataset_id):
            raise StorageError("invalid_dataset_id")
        if type(snapshot_id) is not str or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise StorageError("invalid_snapshot_id")
        with self._transaction():
            return self._load(dataset_id, snapshot_id)

    def _load(self, dataset_id, snapshot_id):
        source = self.connection.execute(
            "SELECT fingerprint,original_sha256,raw_csv FROM s9_sources "
            "WHERE namespace=? AND dataset_id=?",
            (self.namespace, dataset_id),
        ).fetchone()
        row = self.connection.execute(
            "SELECT report_sha256,report,config,tags FROM s9_reports "
            "WHERE namespace=? AND dataset_id=? AND snapshot_id=?",
            (self.namespace, dataset_id, snapshot_id),
        ).fetchone()
        if source is None or row is None:
            raise StorageError("retained_report_not_found")
        try:
            dataset = ingest_csv(bytes(source[2]))
            if (dataset.fingerprint, dataset.original_sha256) != source[:2]:
                raise StorageError("source_tamper")
            raw = bytes(row[1])
            if len(raw) > MAX_REPORT_BYTES or hashlib.sha256(raw).hexdigest() != row[0]:
                raise StorageError("report_tamper")
            document, config_doc = json.loads(raw), json.loads(row[2])
            config = AnalysisConfig(clock=config_doc["clock"])
            if _json(config.document()).decode("utf-8") != row[2]:
                raise StorageError("config_tamper")
            tags = (
                None
                if row[3] is None
                else tuple(TagProvenance.model_validate(value) for value in json.loads(row[3]))
            )
            created_at = datetime.fromisoformat(document["snapshot"]["created_at"])
            report = compute_metrics(dataset, config, tag_provenance=tags, created_at=created_at)
            if report.snapshot.snapshot_id != snapshot_id or _report_bytes(report) != raw:
                raise StorageError("report_recompute_mismatch")
            return Retained(dataset_id, dataset, report, row[0])
        except (ValueError, TypeError, KeyError) as error:
            if isinstance(error, StorageError):
                raise
            raise StorageError("retained_data_invalid") from None
