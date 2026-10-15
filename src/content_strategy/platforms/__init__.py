"""Supported target checks. X remains unavailable until its verified parser is installed."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetCheck:
    supported: bool
    valid: bool
    units: int | None
    reason: str | None


def check_target(scope: str, text: str) -> TargetCheck:
    if scope == "x":
        return TargetCheck(False, False, None, "verified_x_parser_unavailable")
    if scope != "linkedin":
        return TargetCheck(False, False, None, "unsupported_platform")
    try:
        units = len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return TargetCheck(True, False, None, "invalid_unicode")
    return TargetCheck(
        True, units <= 3000, units, None if units <= 3000 else "linkedin_utf16_limit"
    )
