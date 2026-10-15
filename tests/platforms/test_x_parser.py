"""Pinned required official v3/URL/TLD cases; original vectors are never rewritten."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from content_strategy.vendor.twitter_text import (
    extract_urls,
    extract_urls_with_indices,
    parse_tweet,
)

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "conformance/vendor/twitter-text-official"
VALIDATE = yaml.safe_load((OFFICIAL / "validate.yml").read_bytes())["tests"]
EXTRACT = yaml.safe_load((OFFICIAL / "extract.yml").read_bytes())["tests"]
TLDS = yaml.safe_load((OFFICIAL / "tlds.yml").read_bytes())["tests"]


def _cases():
    result = []
    groups = [
        ("validate/" + name, VALIDATE[name], "weighted")
        for name in (
            "WeightedTweetsWithDiscountedEmojiCounterTest",
            "UnicodeDirectionalMarkerCounterTest",
        )
    ]
    groups += [
        ("extract/" + name, EXTRACT[name], "urls") for name in ("urls", "tco_urls_with_params")
    ]
    groups.append(
        (
            "extract/urls_with_directional_markers",
            EXTRACT["urls_with_directional_markers"],
            "indices",
        )
    )
    groups.append(("extract/urls_with_indices", EXTRACT["urls_with_indices"], "indices"))
    groups += [("tlds/" + name, rows, "urls") for name, rows in TLDS.items()]
    for name, rows, method in groups:
        for index, row in enumerate(rows):
            result.append(pytest.param(method, row["text"], row["expected"], id=f"{name}/{index}"))
    return result


@pytest.mark.parametrize(("method", "text", "expected"), _cases())
def test_required_official_vectors(method, text, expected):
    if method == "weighted":
        actual = parse_tweet(text).asdict()
    elif method == "indices":
        actual = extract_urls_with_indices(text)
    else:
        actual = extract_urls(text)
    assert actual == expected


@pytest.mark.parametrize(
    ("text", "valid", "length"),
    [
        pytest.param("a" * 280, True, 280, id="ascii280"),
        pytest.param("a" * 281, False, 281, id="ascii281"),
        pytest.param("漢" * 140, True, 280, id="CJK140"),
        pytest.param("漢" * 141, False, 282, id="CJK141"),
        pytest.param("😀" * 140, True, 280, id="emoji140"),
        pytest.param("😀" * 141, False, 282, id="emoji141"),
        pytest.param("hello\ufeff", False, None, id="invalid-BOM"),
        pytest.param("hello\ufffe", False, None, id="invalid-FFFE"),
    ],
)
def test_required_synthetic_boundaries(text, valid, length):
    parsed = parse_tweet(text)
    assert parsed.valid == valid
    if length is not None:
        assert parsed.weightedLength == length


def test_exact_thirty_eight_source_members_and_complete_license():
    provenance = json.loads(
        (ROOT / "conformance/vendor/twitter-text-parser/PROVENANCE.json").read_text()
    )
    assert len(provenance["members"]) == 38
    for member in provenance["members"]:
        assert (
            hashlib.sha256((ROOT / member["target"]).read_bytes()).hexdigest()
            == member["derived_sha256"]
        )
    notice = (ROOT / "src/content_strategy/vendor/LICENSE.twitter-text-parser").read_bytes()
    assert hashlib.sha256(notice).hexdigest() == provenance["license_sha256"]
