import hashlib
import sqlite3

import pytest

from content_strategy.ingest import IngestError
from content_strategy.metrics import AnalysisConfig
from content_strategy.shared.grounded.models import TagProvenance
from content_strategy.storage import SourceStore, StorageError


def csv_bytes():
    header = "post_id,date,platform,text,impressions,likes,comments,shares\n"
    return (
        header
        + "".join(f"p{i},2026-10-14T01:00:00+02:00,linkedin,hello,100,10,0,0\n" for i in range(6))
    ).encode()


def counts(store):
    return tuple(
        store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ["s9_sources", "s9_reports"]
    )


def test_exact_source_uuid_report_and_restart_without_activation_or_approval(tmp_path):
    path = tmp_path / "store.sqlite3"
    with SourceStore(path, namespace="user") as store:
        retained = store.import_csv(csv_bytes())
        duplicate = store.import_csv(csv_bytes())
        assert duplicate == retained and counts(store) == (1, 1)
        assert retained.dataset_id.startswith("s9-dataset-")
        assert retained.dataset.original_sha256 == hashlib.sha256(csv_bytes()).hexdigest()
        assert store.connection.execute("SELECT COUNT(*) FROM grounded_events").fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM grounded_versions").fetchone()[0] == 0
    with SourceStore(path, namespace="user") as store:
        assert store.load(retained.dataset_id, retained.report.snapshot.snapshot_id) == retained


def test_byte_variants_preserve_original_provenance_separate_from_canonical_identity(tmp_path):
    with SourceStore(tmp_path / "store", namespace="user") as store:
        first = store.import_csv(csv_bytes())
        second = store.import_csv(b"\xef\xbb\xbf" + csv_bytes())
        assert first.dataset_id != second.dataset_id
        assert first.dataset.fingerprint == second.dataset.fingerprint
        assert first.dataset.original_sha256 != second.dataset.original_sha256
        assert first.report.snapshot.snapshot_id == second.report.snapshot.snapshot_id
        assert counts(store) == (2, 2)


def test_config_variants_share_source_but_keep_both_exact_historical_reports(tmp_path):
    with SourceStore(tmp_path / "store", namespace="user") as store:
        first = store.import_csv(csv_bytes())
        second = store.import_csv(csv_bytes(), config=AnalysisConfig("fixed-utc"))
        assert first.dataset_id == second.dataset_id
        assert first.report.snapshot.snapshot_id != second.report.snapshot.snapshot_id
        assert store.load(first.dataset_id, first.report.snapshot.snapshot_id) == first
        assert counts(store) == (1, 2)


def test_namespace_cannot_read_another_retained_id(tmp_path):
    path = tmp_path / "store"
    with SourceStore(path, namespace="alice") as store:
        value = store.import_csv(csv_bytes())
    with SourceStore(path, namespace="bob") as store:
        with pytest.raises(StorageError, match="retained_report_not_found"):
            store.load(value.dataset_id, value.report.snapshot.snapshot_id)
        own = store.import_csv(csv_bytes())
        assert own.dataset_id != value.dataset_id


def test_invalid_upload_and_complete_report_cap_are_atomic(tmp_path, monkeypatch):
    with SourceStore(tmp_path / "store", namespace="user") as store:
        with pytest.raises(IngestError):
            store.import_csv(csv_bytes() + b"broken\n")
        assert counts(store) == (0, 0)
        monkeypatch.setattr("content_strategy.storage.MAX_REPORT_BYTES", 1)
        with pytest.raises(StorageError, match="report_byte_limit"):
            store.import_csv(csv_bytes())
        assert counts(store) == (0, 0)


def test_actual_sql_failure_after_source_insert_rolls_back_both_tables(tmp_path):
    with SourceStore(tmp_path / "store", namespace="user") as store:

        def deny_report(action, table, *rest):
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and table == "s9_reports"
                else sqlite3.SQLITE_OK
            )

        store.connection.set_authorizer(deny_report)
        with pytest.raises(sqlite3.DatabaseError):
            store.import_csv(csv_bytes())
        store.connection.set_authorizer(None)
        assert counts(store) == (0, 0)


@pytest.mark.parametrize("table", ["s9_sources", "s9_reports"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "REPLACE"])
def test_append_only_guards_include_actual_replace_with_recursive_triggers_off(
    tmp_path, table, action
):
    with SourceStore(tmp_path / "store", namespace="user") as store:
        store.import_csv(csv_bytes())
        store.connection.execute("PRAGMA recursive_triggers=OFF")
        sql = (
            f"DELETE FROM {table}"
            if action == "DELETE"
            else (
                f"UPDATE {table} SET namespace=namespace"
                if action == "UPDATE"
                else f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"
            )
        )
        with pytest.raises(sqlite3.IntegrityError, match="s9_append_only"):
            store.connection.execute(sql)
        assert counts(store) == (1, 1)


def test_schema_tamper_refused_before_repair_on_use_and_restart(tmp_path):
    path = tmp_path / "store"
    with SourceStore(path, namespace="user") as store:
        value = store.import_csv(csv_bytes())
        store.connection.execute("DROP TRIGGER s9_reports_update")
        with pytest.raises(StorageError, match="storage_schema_tamper"):
            store.load(value.dataset_id, value.report.snapshot.snapshot_id)
    with pytest.raises(StorageError, match="storage_schema_tamper"):
        SourceStore(path, namespace="user")


def test_same_schema_report_byte_tamper_detected_even_after_guard_restoration(tmp_path):
    with SourceStore(tmp_path / "store", namespace="user") as store:
        value = store.import_csv(csv_bytes())
        sql = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='s9_reports_update'"
        ).fetchone()[0]
        store.connection.execute("DROP TRIGGER s9_reports_update")
        store.connection.execute("UPDATE s9_reports SET report=?", (b"{}",))
        store.connection.execute(sql)
        with pytest.raises(StorageError, match="report_tamper"):
            store.load(value.dataset_id, value.report.snapshot.snapshot_id)


@pytest.mark.parametrize("namespace", ["", "../user", "user name", "x" * 65])
def test_namespace_validated_before_database_creation(tmp_path, namespace):
    path = tmp_path / "absent"
    with pytest.raises(StorageError, match="invalid_namespace"):
        SourceStore(path, namespace=namespace)
    assert not path.exists()


def test_tag_provenance_is_retained_and_recomputed_without_mutating_original_source(tmp_path):
    tags = tuple(
        TagProvenance(
            source_id=f"p{i}",
            field=field,
            value="education" if field == "topic" else "text",
            method="keyword",
            taxonomy_version="test/1",
        )
        for i in range(6)
        for field in ("topic", "format")
    )
    with SourceStore(tmp_path / "store", namespace="user") as store:
        baseline = store.import_csv(csv_bytes())
        tagged = store.import_csv(csv_bytes(), tag_provenance=tags)
        assert baseline.dataset == tagged.dataset
        assert baseline.dataset_id == tagged.dataset_id
        assert baseline.report.snapshot.snapshot_id != tagged.report.snapshot.snapshot_id
        assert store.load(tagged.dataset_id, tagged.report.snapshot.snapshot_id) == tagged
        assert counts(store) == (1, 2)


def test_two_actual_connections_race_keeps_one_exact_dataset_and_report(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "store"
    # Bootstrap serially; each worker then owns its actual connection.
    SourceStore(path, namespace="user").close()
    barrier = Barrier(2)

    def worker():
        with SourceStore(path, namespace="user") as store:
            barrier.wait(timeout=10)
            result = store.import_csv(csv_bytes())
            return result.dataset_id, result.report_sha256

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: worker(), range(2)))
    assert outcomes[0] == outcomes[1]
    with SourceStore(path, namespace="user") as store:
        assert counts(store) == (1, 1)
