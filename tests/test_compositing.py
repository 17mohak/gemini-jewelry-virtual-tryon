"""Tests for the pixel-preserving compositing post-process.

These run entirely offline on synthetic arrays/images (no API, no network).
They pin the two properties the realism story depends on:

  * outside the edited region the result is the ORIGINAL photo (identity,
    background, grain preserved) — not the model's re-synthesis; and
  * the model's global exposure/white-balance drift is neutralized.

Plus the safety valves that guarantee the post-process can never make an output
worse than the raw model baseline it replaces.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from backend.services import compositing as C


@pytest.fixture
def base_array() -> np.ndarray:
    """A textured gray photo (with grain) so noise-matching has signal."""
    rng = np.random.default_rng(42)
    base = np.full((200, 200, 3), 120.0, dtype=np.float32)
    base += rng.normal(0, 6, base.shape).astype(np.float32)  # sensor grain
    # a gentle vignette so tone-harmonization has structure to fit
    yy = np.linspace(-1, 1, 200)[:, None]
    base += (yy * 12).astype(np.float32)
    return np.clip(base, 0, 255)


def _model_with_edit(base: np.ndarray, brightness_drift: float = 12.0) -> np.ndarray:
    """Simulate Nano Banana: globally re-grade, then add a 'jewelry' block."""
    model = np.clip(base + brightness_drift, 0, 255)  # global exposure drift
    model[80:120, 85:115] = [205.0, 60.0, 55.0]        # the local edit
    return model


# ── Color science ─────────────────────────────────────────────────────────────

def test_rgb_to_lab_reference_points():
    px = np.array([[[255, 255, 255], [0, 0, 0], [255, 0, 0]]], dtype=np.float32)
    lab = C.rgb_to_lab(px)
    # White -> L≈100, a≈b≈0; black -> L≈0.
    assert lab[0, 0, 0] == pytest.approx(100.0, abs=0.5)
    assert abs(lab[0, 0, 1]) < 0.5 and abs(lab[0, 0, 2]) < 0.5
    assert lab[0, 1, 0] == pytest.approx(0.0, abs=0.5)
    # Pure red has a strongly positive a*.
    assert lab[0, 2, 1] > 60


# ── Core compositing behavior ─────────────────────────────────────────────────

def test_outside_edit_is_the_original(base_array):
    model = _model_with_edit(base_array)
    out, info = C.composite_arrays(base_array, model)
    assert info["applied"]
    out = out.astype(np.float32)

    # Far from the edit (top strip), the composite must equal the ORIGINAL
    # photo, not the brightened model: drift is gone and pixels are untouched.
    top = slice(0, 40)
    assert np.abs(out[top] - base_array[top]).mean() < 1.0
    assert np.abs(out[top] - model[top]).mean() > 5.0  # clearly not the model


def test_edit_region_keeps_the_jewelry(base_array):
    model = _model_with_edit(base_array)
    out, info = C.composite_arrays(base_array, model)
    out = out.astype(np.float32)
    # The centre of the block is reddish, sourced from the model, not gray base.
    centre = out[95:105, 95:105]
    assert centre[..., 0].mean() > 150          # red channel high
    assert centre[..., 1].mean() < 110          # green channel low
    # And it is far from the original gray there.
    assert np.abs(centre - base_array[95:105, 95:105]).mean() > 40


def test_edit_fraction_is_small_and_localized(base_array):
    model = _model_with_edit(base_array)
    _out, info = C.composite_arrays(base_array, model)
    # The 40x30 block (+dilation) is a small fraction of the 200x200 frame.
    assert 0.005 < info["edit_fraction"] < 0.20


def test_global_brightness_drift_is_neutralized(base_array):
    model = _model_with_edit(base_array, brightness_drift=20.0)
    out, _info = C.composite_arrays(base_array, model)
    out = out.astype(np.float32)
    # Measure mean luma drift OUTSIDE the edit block.
    mask = np.ones((200, 200), bool)
    mask[70:130, 75:125] = False
    drift = out[mask].mean() - base_array[mask].mean()
    assert abs(drift) < 1.5  # the +20 global drift is removed


# ── Safety valves ─────────────────────────────────────────────────────────────

def test_empty_change_bails_to_raw(base_array):
    out, info = C.composite_arrays(base_array, base_array.copy())
    assert not info["applied"]
    assert info["reason"] == "empty change mask"


def test_huge_change_bails_to_raw(base_array):
    rng = np.random.default_rng(0)
    noise = rng.uniform(0, 255, base_array.shape).astype(np.float32)
    out, info = C.composite_arrays(base_array, noise)
    assert not info["applied"]
    assert "too large" in info["reason"]
    # Bail returns the raw model output unchanged.
    assert np.abs(out.astype(np.float32) - noise).mean() < 1.0


def test_aspect_mismatch_bails(tmp_path):
    base = Image.new("RGB", (160, 160), (120, 120, 120))
    base_path = tmp_path / "base.jpg"
    base.save(base_path)
    # A model output with a different aspect ratio (re-cropped scene).
    buf = io.BytesIO()
    Image.new("RGB", (240, 120), (10, 200, 10)).save(buf, "PNG")
    res = C.composite_bytes(base_path, buf.getvalue())
    assert not res.applied
    assert res.reason == "aspect mismatch"
    assert res.image.size == (240, 120)  # native model framing, not warped


# ── End-to-end bytes round trip ───────────────────────────────────────────────

def test_composite_bytes_preserves_resolution_and_mime(tmp_path):
    rng = np.random.default_rng(7)
    arr = np.clip(np.full((256, 256, 3), 120.0) + rng.normal(0, 6, (256, 256, 3)), 0, 255)
    base_im = Image.fromarray(arr.astype(np.uint8))
    base_path = tmp_path / "base.jpg"
    base_im.save(base_path, "JPEG", quality=95)

    model = arr + 15
    model[100:150, 100:150] = [200, 60, 60]
    buf = io.BytesIO()
    Image.fromarray(np.clip(model, 0, 255).astype(np.uint8)).save(buf, "PNG")

    res = C.composite_bytes(base_path, buf.getvalue())
    assert res.applied
    assert res.image.size == base_im.size

    data, mime = C.composite_to_bytes(res, "image/png")
    assert mime == "image/png"
    assert Image.open(io.BytesIO(data)).size == base_im.size
    data, mime = C.composite_to_bytes(res, "image/jpeg")
    assert mime == "image/jpeg"
