"""Atomic upload boundaries; synthetic inline records, never a held-out corpus."""

import csv
import hashlib
import io
import json
from dataclasses import replace
from datetime import date, datetime

import pytest

from content_strategy.ingest import MAX_BYTES, Dataset, IngestError, PostRow, ingest_csv

HEADERS = ["post_id", "date", "platform", "text", "impressions", "likes", "comments", "shares"]
BASE = ["p1", "2026-10-14", " X ", "hello", "10", "1", "0", "0"]


def upload(rows=None, *, headers=None, bom=False, newline="\r\n"):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator=newline)
    writer.writerow(HEADERS if headers is None else headers)
    writer.writerows([BASE] if rows is None else rows)
    return ("\ufeff" if bom else "").encode() + stream.getvalue().encode()


def rejected(payload, code):
    with pytest.raises(IngestError) as caught:
        ingest_csv(payload)
    assert code in {issue.code for issue in caught.value.issues}
    return caught.value


def test_bom_crlf_original_digest_normalized_identity_and_inert_text():
    text = '=HYPERLINK("https://example.invalid/", "click")\n+SUM(1,2)'
    source = BASE.copy()
    source[3] = text
    first = upload([source], bom=True)
    second = upload([source], newline="\n")
    a, b = ingest_csv(first), ingest_csv(second)
    assert a.original_sha256 == hashlib.sha256(first).hexdigest()
    assert a.original_sha256 != b.original_sha256
    assert a.fingerprint == b.fingerprint
    assert a.rows[0].text == text
    assert a.rows[0].platform == "x"
    assert a.rows[0].topic is a.rows[0].format is None
    assert type(a.rows[0].date) is date


@pytest.mark.parametrize("value", ["-1", "1.0", "1e2", "", " 1", "+1", "١", "True"])
def test_one_invalid_integer_rejects_whole_upload_without_source_echo(value):
    bad = ["private-bad-id", *BASE[1:]]
    bad[5] = value
    error = rejected(upload([BASE, bad]), "invalid_integer")
    assert "private-bad-id" not in str(error)
    assert error.issues[0].record == 3
    assert error.issues[0].column == "likes"


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-14T12:30",
        "2026-10-14T12:30:00",
        "2026-02-30",
        "2026-10-14 12:30Z",
        "2026-10-14T12:30+25:00",
    ],
)
def test_invalid_date_or_naive_timestamp_rejects(value):
    row = BASE.copy()
    row[1] = value
    rejected(upload([row]), "invalid_date_or_offset")


@pytest.mark.parametrize("value", ["2026-10-14T12:30Z", "2026-10-14T12:30:05.123456-04:00"])
def test_offset_timestamp_preserved(value):
    row = BASE.copy()
    row[1] = value
    assert isinstance(ingest_csv(upload([row])).rows[0].date, datetime)


def test_nfc_duplicate_id_rejects_and_case_distinct_ids_remain_distinct():
    a, b = BASE.copy(), BASE.copy()
    a[0], b[0] = "e\u0301", "é"
    rejected(upload([a, b]), "duplicate_id")
    a[0], b[0] = "A", "a"
    assert len(ingest_csv(upload([a, b])).rows) == 2


@pytest.mark.parametrize("headers", [HEADERS[:-1], HEADERS + ["surprise"], HEADERS + ["likes"]])
def test_header_schema_rejects(headers):
    rejected(upload(headers=headers), "invalid_schema")


def test_optional_labels_and_unknown_platform_are_explicit_supplied_data():
    row = BASE.copy()
    row[2] = " Other Network "
    row += [" e\u0301 ", "  "]
    parsed = ingest_csv(upload([row], headers=HEADERS + ["topic", "format"]))
    assert parsed.rows[0].platform == "other network"
    assert parsed.rows[0].topic == "é"
    assert parsed.rows[0].format is None


def test_byte_row_and_text_bounds_are_inclusive():
    rejected(b"x" * (MAX_BYTES + 1), "byte_limit")
    rows = [[f"p{i}", *BASE[1:]] for i in range(5000)]
    assert len(ingest_csv(upload(rows)).rows) == 5000
    rejected(upload(rows + [["extra", *BASE[1:]]]), "row_limit")
    row = BASE.copy()
    row[3] = "x" * 4000
    assert len(ingest_csv(upload([row])).rows[0].text) == 4000
    row[3] += "x"
    rejected(upload([row]), "text_limit")


def test_raw_and_nfc_text_expansion_bounds_and_canonical_identity():
    row = BASE.copy()
    row[3] = "\u0344" * 2001  # Each becomes two code points in NFC.
    rejected(upload([row]), "text_limit")
    row[3] = "e\u0301"
    a = ingest_csv(upload([row]))
    row[3] = "é"
    b = ingest_csv(upload([row]))
    assert a.fingerprint == b.fingerprint
    assert a.rows[0].text != b.rows[0].text


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"\xff", "invalid_utf8"),
        (b"", "invalid_schema"),
        (upload([]), "empty_dataset"),
        (upload([BASE[:-1]]), "column_count"),
        (upload() + b'"unterminated', "csv_syntax"),
        ("text", "bytes_required"),
    ],
)
def test_invalid_envelope_is_atomic(payload, code):
    rejected(payload, code)


@pytest.mark.parametrize(
    "change", [{"likes": True}, {"likes": -1}, {"date": datetime(2026, 10, 14)}, {"post_id": " p1"}]
)
def test_programmatic_rows_cannot_bypass_validation(change):
    row = PostRow("p1", date(2026, 10, 14), "x", "text", 10, 1, 0, 0)
    with pytest.raises(ValueError):
        replace(row, **change)


def test_dataset_is_immutable_unique_nonempty_validated_rows():
    row = PostRow("p1", date(2026, 10, 14), "x", "text", 10, 1, 0, 0)
    for rows in [(), (row, row), (object(),)]:
        with pytest.raises(ValueError):
            Dataset(rows, "0" * 64)
    with pytest.raises(ValueError):
        Dataset((row,), "not-a-hash")


def test_128_digit_boundary_and_129_atomic_rejection_including_leading_zeros():
    row = BASE.copy()
    row[4] = "9" * 128
    parsed = ingest_csv(upload([row]))
    assert parsed.rows[0].impressions == 10**128 - 1
    for raw in ("9" * 129, "0" * 128 + "1"):
        row[0], row[4] = "bad", raw
        issue = rejected(upload([BASE, row]), "numeric_limit").issues[0]
        assert (issue.record, issue.column) == (3, "impressions")
    with pytest.raises(ValueError, match="numeric_limit"):
        replace(parsed.rows[0], likes=10**128)


def test_numeric_successor_preserves_existing_wp01_canonical_bytes():
    expected = {
        "identity_version": "dataset-identity.v1",
        "id_field": "post_id",
        "rows": [
            {
                "post_id": "p1",
                "date": "2026-10-14",
                "platform": "x",
                "text": "hello",
                "impressions": 10,
                "likes": 1,
                "comments": 0,
                "shares": 0,
                "topic": None,
                "format": None,
            }
        ],
    }
    canonical = json.dumps(expected, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert ingest_csv(upload()).fingerprint == hashlib.sha256(canonical.encode()).hexdigest()


def test_exact_10_mib_upload_accepted_without_changing_global_csv_limit():
    rows = [[f"p{i}", *BASE[1:]] for i in range(5000)]
    # Fill to the exact byte boundary while keeping every text cell below 4,000 code points.
    remaining = MAX_BYTES - len(upload(rows))
    for row in rows:
        extra = min(remaining, 4000 - len(row[3]))
        row[3] += "x" * extra
        remaining -= extra
    assert remaining == 0
    payload = upload(rows)
    assert len(payload) == MAX_BYTES
    before = csv.field_size_limit()
    assert len(ingest_csv(payload).rows) == 5000
    assert csv.field_size_limit() == before
    rejected(payload + b"\n", "byte_limit")
