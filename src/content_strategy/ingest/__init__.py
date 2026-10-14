"""Atomic bounded CSV parsing in memory; no files, providers or storage are opened."""

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

from ..shared.grounded import dataset_fingerprint

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_TEXT = 4000
MAX_COUNT_DIGITS = 128
INPUT_CONTRACT_VERSION = "csv.v2-bounded-counts"
REQUIRED = frozenset(
    {"post_id", "date", "platform", "text", "impressions", "likes", "comments", "shares"}
)
OPTIONAL = frozenset({"topic", "format"})
COUNTS = ("impressions", "likes", "comments", "shares")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
    r"(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


@dataclass(frozen=True)
class InputIssue:
    record: int
    column: str
    code: str


class IngestError(ValueError):
    """Safe diagnostics only; no source-cell values appear in exception messages."""

    def __init__(self, issues: tuple[InputIssue, ...]):
        self.issues = issues[:100]
        super().__init__(
            "CSV rejected atomically: " + ",".join(issue.code for issue in self.issues)
        )


def _label(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid_label")
    value = unicodedata.normalize("NFC", value.strip())
    if len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid_label")
    return value or None


@dataclass(frozen=True)
class PostRow:
    post_id: str
    date: date | datetime
    platform: str
    text: str
    impressions: int
    likes: int
    comments: int
    shares: int
    topic: str | None = None
    format: str | None = None

    def __post_init__(self):
        if not isinstance(self.post_id, str):
            raise ValueError("invalid_id")
        post_id = unicodedata.normalize("NFC", self.post_id)
        if (
            not post_id
            or len(post_id) > 256
            or post_id != post_id.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in post_id)
        ):
            raise ValueError("invalid_id")
        object.__setattr__(self, "post_id", post_id)
        if not isinstance(self.platform, str):
            raise ValueError("invalid_platform")
        platform = unicodedata.normalize("NFC", self.platform.strip().casefold())
        if (
            not platform
            or len(platform) > 64
            or any(ord(c) < 32 or ord(c) == 127 for c in platform)
        ):
            raise ValueError("invalid_platform")
        object.__setattr__(self, "platform", platform)
        if not isinstance(self.text, str) or any(
            len(text) > MAX_TEXT for text in (self.text, unicodedata.normalize("NFC", self.text))
        ):
            raise ValueError("text_limit")
        if isinstance(self.date, datetime):
            if self.date.tzinfo is None or self.date.utcoffset() is None:
                raise ValueError("offset_required")
        elif type(self.date) is not date:
            raise ValueError("invalid_date")
        for field in COUNTS:
            if type(getattr(self, field)) is not int or getattr(self, field) < 0:
                raise ValueError("invalid_integer")
            if getattr(self, field) >= 10**MAX_COUNT_DIGITS:
                raise ValueError("numeric_limit")
        object.__setattr__(self, "topic", _label(self.topic))
        object.__setattr__(self, "format", _label(self.format))

    def identity_row(self) -> dict[str, object]:
        return {
            "post_id": self.post_id,
            "date": self.date.isoformat(),
            "platform": self.platform,
            "text": self.text,
            "impressions": self.impressions,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "topic": self.topic,
            "format": self.format,
        }

    @property
    def interactions(self) -> int:
        return self.likes + self.comments + self.shares


@dataclass(frozen=True)
class Dataset:
    rows: tuple[PostRow, ...]
    original_sha256: str

    def __post_init__(self):
        if type(self.rows) is not tuple or not 1 <= len(self.rows) <= MAX_ROWS:
            raise ValueError("dataset_row_limit")
        if any(type(row) is not PostRow for row in self.rows):
            raise ValueError("invalid_row")
        ids = [row.post_id for row in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_id")
        if not isinstance(self.original_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.original_sha256
        ):
            raise ValueError("invalid_original_hash")

    @property
    def fingerprint(self) -> str:
        return dataset_fingerprint([row.identity_row() for row in self.rows], id_field="post_id")


def _temporal(value: str) -> date | datetime:
    if len(value) > 64:
        raise ValueError("invalid_date")
    if DATE.fullmatch(value):
        return date.fromisoformat(value)
    if not TIMESTAMP.fullmatch(value):
        raise ValueError("offset_timestamp_or_date_required")
    return datetime.fromisoformat(value)


def ingest_csv(payload: bytes) -> Dataset:
    """All records validate before any Dataset is returned. IDs are NFC/case-preserving."""
    if type(payload) is not bytes:
        raise IngestError((InputIssue(0, "file", "bytes_required"),))
    if len(payload) > MAX_BYTES:
        raise IngestError((InputIssue(0, "file", "byte_limit"),))
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise IngestError((InputIssue(0, "file", "invalid_utf8"),)) from error
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader, [])
        if (
            not REQUIRED.issubset(headers)
            or set(headers) - REQUIRED - OPTIONAL
            or len(headers) != len(set(headers))
        ):
            raise IngestError((InputIssue(1, "header", "invalid_schema"),))
        rows = []
        issues = []
        ids = set()
        records = 0
        for number, fields in enumerate(reader, 2):
            if not fields:
                continue
            records += 1
            if records > MAX_ROWS:
                issues.append(InputIssue(number, "file", "row_limit"))
                break
            if len(fields) != len(headers):
                issues.append(InputIssue(number, "row", "column_count"))
                continue
            source = dict(zip(headers, fields, strict=True))
            values: dict[str, object] = {}
            for column in COUNTS:
                try:
                    if not re.fullmatch(r"[0-9]+", source[column]):
                        raise ValueError("invalid_integer")
                    if len(source[column]) > MAX_COUNT_DIGITS:
                        issues.append(InputIssue(number, column, "numeric_limit"))
                        continue
                    values[column] = int(source[column])
                except ValueError:
                    issues.append(InputIssue(number, column, "invalid_integer"))
            try:
                values["date"] = _temporal(source["date"])
            except ValueError:
                issues.append(InputIssue(number, "date", "invalid_date_or_offset"))
            if len(values) != 5:
                continue
            try:
                row = PostRow(
                    **values,
                    post_id=source["post_id"],
                    platform=source["platform"],
                    text=source["text"],
                    topic=source.get("topic"),
                    format=source.get("format"),
                )
            except ValueError as error:
                issues.append(InputIssue(number, "row", str(error)))
                continue
            if row.post_id in ids:
                issues.append(InputIssue(number, "post_id", "duplicate_id"))
            else:
                ids.add(row.post_id)
                rows.append(row)
        if not records:
            issues.append(InputIssue(2, "file", "empty_dataset"))
        if issues:
            raise IngestError(tuple(issues))
        return Dataset(tuple(rows), hashlib.sha256(payload).hexdigest())
    except csv.Error as error:
        raise IngestError((InputIssue(reader.line_num, "row", "csv_syntax"),)) from error


__all__ = ["Dataset", "IngestError", "InputIssue", "PostRow", "ingest_csv"]
