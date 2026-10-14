"""Versioned canonical identity only; no ingestion, arithmetic or storage engine."""

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

DECIMAL_PATTERN = r"-?(?:0|[1-9][0-9]{0,31})(?:\.[0-9]{1,8})?"


def canonical_decimal(value: Decimal) -> str:
    """Represent a finite exact decimal without exponent, negative zero or rounding."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(
            "Expected a finite Decimal; floats and token estimates are not exact values"
        )
    parts = value.as_tuple()
    if len(parts.digits) > 256 or abs(int(parts.exponent)) > 256:
        raise ValueError("Decimal representation exceeds the identity bound")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not re.fullmatch(DECIMAL_PATTERN, text):
        raise ValueError(
            "Decimal needs at most 32 integer and 8 fractional digits; never round here"
        )
    return text


def exact_decimal(value: object) -> Decimal:
    """Accept exact Python Decimal or decimal-string wire values, never numeric coercion."""
    if isinstance(value, str):
        if not re.fullmatch(DECIMAL_PATTERN, value):
            raise ValueError("Use a bounded plain decimal string, without exponent or rounding")
        value = Decimal(value)
    if not isinstance(value, Decimal):
        raise ValueError("Use Decimal or an exact decimal string, not float/int/bool")
    return Decimal(canonical_decimal(value))


def normalized_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string without coercion")
    return unicodedata.normalize("NFC", value)


def _normalized(value: object) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return normalized_string(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Identity object keys must be strings")
            normalized_key = normalized_string(key)
            if normalized_key in output:
                raise ValueError("Duplicate identity key after NFC normalization")
            output[normalized_key] = _normalized(item)
        return output
    if isinstance(value, (tuple, list)):
        return [_normalized(item) for item in value]
    raise ValueError(
        "Identity accepts JSON values and exact Decimal, not float/datetime/SDK objects"
    )


def canonical_json(value: object) -> str:
    return json.dumps(_normalized(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def identity_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output = {}
    for key, value in pairs:
        key = normalized_string(key)
        if key in output:
            raise ValueError("Duplicate JSON key after NFC normalization")
        output[key] = value
    return output


def _reject_float(value: str) -> None:
    raise ValueError("Configuration decimals must be explicit strings, not JSON float numbers")


def canonical_config(value: object) -> str:
    """Store config as immutable canonical JSON text; reject duplicate keys and floats."""
    if not isinstance(value, str) or len(value.encode("utf-8")) > 32768:
        raise ValueError("Config must be an object encoded as at most 32768 UTF-8 bytes")
    parsed = json.loads(
        value,
        object_pairs_hook=_unique_object,
        parse_float=_reject_float,
        parse_constant=_reject_float,
    )
    if not isinstance(parsed, dict):
        raise ValueError("Config identity requires a JSON object")
    return canonical_json(parsed)


def dataset_fingerprint(rows: Sequence[Mapping[str, object]], *, id_field: str) -> str:
    """Hash normalized source rows by unique ID; does not validate or compute CSV metrics."""
    id_field = normalized_string(id_field)
    if not id_field:
        raise ValueError("An explicit source ID field is required")
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes))
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise ValueError("Source rows must be mappings, not text or positional arrays")
    normalized_rows = [_normalized(row) for row in rows]
    seen = set()
    for row in normalized_rows:
        source_id = row.get(id_field)
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("Source IDs must be nonempty unique strings after normalization")
        seen.add(source_id)
    return identity_hash(
        {
            "identity_version": "dataset-identity.v1",
            "id_field": id_field,
            "rows": sorted(normalized_rows, key=lambda row: row[id_field]),
        }
    )


def metric_slugs(keys: Sequence[str]) -> dict[str, str]:
    """Readable slugs; suffix every colliding NFC key, or fail if a collision remains."""
    if not isinstance(keys, Sequence) or isinstance(keys, (str, bytes)):
        raise ValueError("Slug keys require an explicit sequence of strings")
    normalized = sorted({normalized_string(key) for key in keys})
    groups: dict[str, list[str]] = {}
    for key in normalized:
        folded = unicodedata.normalize("NFKC", key).casefold()
        slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "blank"
        groups.setdefault(slug, []).append(key)
    output = {}
    for slug, originals in groups.items():
        for key in originals:
            suffix = "-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]
            output[key] = slug + suffix if len(originals) > 1 else slug
    if len(set(output.values())) != len(output):
        raise ValueError("Slug collision remains; explicit resolution is required")
    return output
