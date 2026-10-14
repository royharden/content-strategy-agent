"""Canonical identity cases are separate from unimplemented analytics and authorization."""

import hashlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

from content_strategy.shared.grounded import (
    SnapshotIdentity,
    TagProvenance,
    canonical_config,
    canonical_decimal,
    canonical_json,
    dataset_fingerprint,
    identity_hash,
    metric_slugs,
)

HASH = "a" * 64


def identity(**changes):
    return SnapshotIdentity(
        **(
            {
                "dataset_fingerprint": HASH,
                "tag_provenance": (),
                "config_json": '{"minimum_n":5,"mode":"posted-local"}',
                "compute_version": "metrics.v1",
            }
            | changes
        )
    )


def tag(source="post-1", **changes):
    return TagProvenance(
        **(
            {
                "source_id": source,
                "field": "topic",
                "value": "analysis",
                "method": "supplied",
                "taxonomy_version": "topics.v1",
            }
            | changes
        )
    )


def test_canonical_json_has_explicit_order_unicode_and_decimal_bytes():
    actual = canonical_json({"z": Decimal("-0.000"), "a": "e\u0301", "n": Decimal("1.2300")})
    assert actual == '{"a":"é","n":"1.23","z":"0"}'
    assert identity_hash({"b": 2, "a": 1}) == hashlib.sha256(b'{"a":1,"b":2}').hexdigest()


@pytest.mark.parametrize("value", [0.1, float("nan"), object(), {1: "bad"}])
def test_nonexact_or_unsupported_identity_types_are_rejected(value):
    with pytest.raises(ValueError):
        canonical_json(value)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("1e-9")])
def test_decimal_never_rounds_or_accepts_nonfinite(value):
    with pytest.raises(ValueError):
        canonical_decimal(value)


def test_dataset_identity_is_row_key_and_unicode_order_invariant():
    rows = [{"post_id": "b", "text": "e\u0301"}, {"post_id": "a", "count": 1}]
    reordered = [{"count": 1, "post_id": "a"}, {"text": "é", "post_id": "b"}]
    assert dataset_fingerprint(rows, id_field="post_id") == dataset_fingerprint(
        reordered, id_field="post_id"
    )
    assert dataset_fingerprint(rows, id_field="post_id") != dataset_fingerprint(
        [*rows[:-1], {"post_id": "a", "count": 2}], id_field="post_id"
    )


@pytest.mark.parametrize(
    "rows",
    [
        [{"post_id": "e\u0301"}, {"post_id": "é"}],
        [{"post_id": "a"}, {"post_id": "a"}],
        [{"post_id": 1}],
        [{"other": "a"}],
        ["not a row"],
        "not rows",
    ],
)
def test_source_identity_rejects_duplicate_normalized_or_missing_ids(rows):
    with pytest.raises(ValueError):
        dataset_fingerprint(rows, id_field="post_id")


def test_config_order_is_canonical_and_rejects_key_collisions():
    assert canonical_config('{"b":2,"a":1}') == '{"a":1,"b":2}'
    for value in ['{"a":1,"a":2}', '{"é":1,"e\\u0301":2}', '{"x":0.1}', "[]"]:
        with pytest.raises(ValueError):
            canonical_config(value)
    with pytest.raises(ValueError):
        canonical_json({"é": 1, "e\u0301": 2})


def test_identity_tracks_config_tags_and_computation_not_input_order():
    base = identity(tag_provenance=(tag("b"), tag("a")))
    equivalent = identity(
        tag_provenance=(tag("a"), tag("b")),
        config_json='{ "mode": "posted-local", "minimum_n": 5 }',
    )
    assert base.snapshot_id == equivalent.snapshot_id
    for changed in [
        identity(config_json='{"minimum_n":6}'),
        identity(tag_provenance=(tag(value="other"),)),
        identity(tag_provenance=(tag(method="jev", model="jev-1.13.0"),)),
        identity(compute_version="metrics.v2"),
        identity(dataset_fingerprint="b" * 64),
    ]:
        assert changed.snapshot_id != base.snapshot_id
    with pytest.raises(ValidationError):
        identity(tag_provenance=(tag(), tag(value="conflict")))


def test_every_slug_collision_gets_order_independent_suffix():
    keys = ["AI tools", "AI-tools", "plain", "é", "e\u0301"]
    slugs = metric_slugs(keys)
    assert slugs == metric_slugs(list(reversed(keys)))
    assert slugs["plain"] == "plain"
    assert slugs["AI tools"] == "ai-tools-" + hashlib.sha256(b"AI tools").hexdigest()[:6]
    assert slugs["AI-tools"] != slugs["AI tools"]
    assert len(slugs) == 4  # NFC-equivalent category labels share one semantic key.
    assert len(set(slugs.values())) == len(slugs)


def test_second_order_slug_collision_fails_instead_of_reusing_evidence_id():
    suffix = hashlib.sha256(b"AI tools").hexdigest()[:6]
    with pytest.raises(ValueError, match="collision remains"):
        metric_slugs(["AI tools", "AI-tools", "ai-tools-" + suffix])


def test_identity_is_deeply_immutable_and_returns_detached_document():
    original = identity(tag_provenance=(tag(),))
    document = original.identity_document()
    document["compute_version"] = "mutated"
    assert original.compute_version == "metrics.v1"
    with pytest.raises(ValidationError):
        original.tag_provenance[0].value = "mutated"


def test_iterator_and_scalar_sources_cannot_silently_lose_identity_rows():
    with pytest.raises(ValueError):
        dataset_fingerprint(iter([{"post_id": "a"}]), id_field="post_id")
    with pytest.raises(ValueError):
        metric_slugs("not a key list")
