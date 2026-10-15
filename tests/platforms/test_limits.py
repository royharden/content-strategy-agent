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


def test_unpaired_surrogate_and_unknown_target_refuse():
    assert not check_target("linkedin", "\ud800").valid
    assert not check_target("x", "\ud800").valid
    assert check_target("x", "short").supported and check_target("x", "short").valid
    assert not check_target("unknown", "body").supported


@pytest.mark.parametrize(
    ("text", "units", "valid"),
    [
        ("a" * 280, 280, True),
        ("a" * 281, 281, False),
        ("漢" * 140, 280, True),
        ("漢" * 141, 282, False),
        ("😀" * 140, 280, True),
        ("😀" * 141, 282, False),
        ("https://example.com/" + "a" * 200, 23, True),
    ],
)
def test_actual_x_target_uses_verified_v3_weighting(text, units, valid):
    result = check_target("x", text)
    assert result.supported and result.units == units and result.valid == valid
