"""Tests for aspect-ratio pinning (no network)."""

import pytest

from backend.services.nanobanana_service import (
    SUPPORTED_ASPECT_RATIOS,
    closest_aspect_ratio,
)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1024, 1024, "1:1"),
        (768, 1024, "3:4"),     # classic portrait
        (1024, 768, "4:3"),     # classic landscape
        (1080, 1920, "9:16"),   # phone portrait
        (1920, 1080, "16:9"),   # phone landscape
        (800, 1200, "2:3"),
        (1200, 800, "3:2"),
        (1000, 1250, "4:5"),    # instagram portrait
        (2520, 1080, "21:9"),   # ultrawide
    ],
)
def test_exact_and_common_ratios(width, height, expected):
    assert closest_aspect_ratio(width, height) == expected


def test_extreme_ratios_clamp_to_nearest_supported():
    # a 4:1 panorama clamps to the widest supported ratio
    assert closest_aspect_ratio(4000, 1000) == "21:9"
    # a 1:4 strip clamps to the tallest supported ratio
    assert closest_aspect_ratio(1000, 4000) == "9:16"


def test_log_space_symmetry():
    """2:1 and 1:2 must resolve to mirrored ratios, not biased ones."""
    wide = closest_aspect_ratio(2000, 1000)
    tall = closest_aspect_ratio(1000, 2000)
    w_num, w_den = (int(x) for x in wide.split(":"))
    t_num, t_den = (int(x) for x in tall.split(":"))
    assert (w_num, w_den) == (t_den, t_num)


def test_degenerate_input_falls_back_to_square():
    assert closest_aspect_ratio(0, 100) == "1:1"
    assert closest_aspect_ratio(100, 0) == "1:1"


def test_all_supported_ratios_are_self_consistent():
    for name, value in SUPPORTED_ASPECT_RATIOS.items():
        num, den = (int(x) for x in name.split(":"))
        assert abs(num / den - value) < 1e-9
        # a synthetic image with exactly this ratio must pick it
        assert closest_aspect_ratio(num * 120, den * 120) == name
