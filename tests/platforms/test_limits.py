import pytest

from content_strategy.platforms import check_target


@pytest.mark.parametrize(
    ("text", "units", "valid"),
    [
        ("x" * 3000, 3000, True),
        ("x" * 3001, 3001, False),
        ("😀" * 1500, 3000, True),
        ("😀" * 1500 + "a", 3001, False),
    ],
)
def test_linkedin_utf16_boundaries(text, units, valid):
    result = check_target("linkedin", text)
    assert result.supported and result.valid is valid and result.units == units


def test_unpaired_surrogate_and_unverified_x_are_not_claimed_supported():
    assert not check_target("linkedin", "\ud800").valid
    assert not check_target("x", "short").supported
    assert check_target("x", "short").reason == "verified_x_parser_unavailable"
    assert not check_target("unknown", "body").supported
