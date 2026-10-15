"""Closed browser inputs: no actor, policy, model judgments, candidate or proof fields."""

import base64
import binascii
import json
from typing import Annotated, Literal

from pydantic import Field

from ..ingest import MAX_BYTES
from ..shared.grounded.models import Identifier, ItemVersion, Record
from .service import Selection

MAX_IMPORT_BODY = 14 * 1024 * 1024
MAX_BODY = 128 * 1024


class ImportInput(Record):
    csv_base64: Annotated[str, Field(max_length=((MAX_BYTES + 2) // 3) * 4)]
    clock: Literal["posted-local", "fixed-utc"] = "posted-local"

    def csv_bytes(self):
        try:
            value = base64.b64decode(self.csv_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("invalid_csv_encoding") from None
        if len(value) > MAX_BYTES:
            raise ValueError("csv_too_large")
        return value


class SelectedInput(Record):
    selection: Selection


class CurrentInput(SelectedInput):
    expected_sequence: Annotated[int, Field(ge=0)]


class PlanInput(CurrentInput):
    brief: Annotated[str, Field(max_length=4000)] = ""


class VersionInput(CurrentInput):
    version: ItemVersion


class DecisionInput(VersionInput):
    approve: bool


class DraftInput(VersionInput):
    brief: Annotated[str, Field(max_length=4000)] = ""


class EditInput(VersionInput):
    text: Annotated[str, Field(min_length=1, max_length=16384)]


class ExportInput(CurrentInput):
    idempotency_key: Identifier
    items: Annotated[tuple[ItemVersion, ...], Field(min_length=1, max_length=100)]


class ReceiptInput(SelectedInput):
    idempotency_key: Identifier


def parse_input(raw: bytes, kind: type[Record]):
    """Reject duplicate fields before the strict JSON boundary converts tuple arrays."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite_json_number")

    try:
        document = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
        if not isinstance(document, dict):
            raise ValueError("json_object_required")
        return kind.model_validate_json(json.dumps(document, ensure_ascii=True, allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        raise ValueError("invalid_request") from None
