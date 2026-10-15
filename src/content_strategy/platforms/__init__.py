"""Verified X v3 weighted checks and conservative LinkedIn UTF-16 checks."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetCheck:
    supported: bool
    valid: bool
    units: int | None
    reason: str | None


def check_target(scope: str, text: str) -> TargetCheck:
    if scope == "x":
        from ..vendor.twitter_text import parse_tweet

        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            return TargetCheck(True, False, None, "invalid_unicode")
        result = parse_tweet(text)
        return TargetCheck(
            True,
            result.valid,
            result.weightedLength,
            None if result.valid else "x_v3_invalid_or_weighted_limit",
        )
    if scope != "linkedin":
        return TargetCheck(False, False, None, "unsupported_platform")
    try:
        units = len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return TargetCheck(True, False, None, "invalid_unicode")
    return TargetCheck(
        True, units <= 3000, units, None if units <= 3000 else "linkedin_utf16_limit"
    )
