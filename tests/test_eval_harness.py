"""Tests for the evaluation harness (no network, no API spend)."""

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval import metrics  # noqa: E402
from eval.run_eval import load_benchmark, load_catalogs, select_cases  # noqa: E402


# ── Benchmark definition ─────────────────────────────────────────────────────

def test_benchmark_covers_every_catalog_item():
    """Every jewelry AND clothing item must have a benchmark case."""
    bench_items = {c["item_id"] for c in load_benchmark()["cases"]}
    catalog_items = set(load_catalogs().keys())
    assert bench_items == catalog_items


def test_benchmark_inputs_exist_and_hard_subset_is_small():
    bench = load_benchmark()
    for path in bench["inputs"].values():
        assert (ROOT / path).exists(), f"missing benchmark input {path}"
    hard = [c for c in bench["cases"] if c.get("hard")]
    assert 4 <= len(hard) <= 8  # small regression subset, not a full sweep
    hard_types = {load_catalogs()[c["item_id"]][0]["type"] for c in hard}
    # the hard subset must exercise all four jewelry types + both Part 2 classes
    assert {"necklace", "earrings", "ring", "bracelet", "dress", "top"} <= hard_types


def test_case_selection_modes():
    bench = load_benchmark()

    class Args:
        cases = None
        all = False

    assert all(c.get("hard") for c in select_cases(bench, Args()))
    Args.all = True
    assert len(select_cases(bench, Args())) == len(bench["cases"])
    Args.all, Args.cases = False, "necklace-cross-pendant"
    assert [c["id"] for c in select_cases(bench, Args())] == ["necklace-cross-pendant"]
    Args.cases = "no-such-case"
    with pytest.raises(SystemExit):
        select_cases(bench, Args())


# ── Metric sanity ────────────────────────────────────────────────────────────

def _save(tmp_path, name, im):
    p = tmp_path / name
    im.save(p, "JPEG", quality=92)
    return p


def test_identical_images_score_clean(tmp_path):
    im = Image.effect_noise((400, 300), 32).convert("RGB")
    a = _save(tmp_path, "a.jpg", im)
    b = _save(tmp_path, "b.jpg", im)
    values, flags = metrics.evaluate_case(a, b, is_clothing=False)
    assert flags == []
    assert values["aspect_drift"] == 0.0
    assert 0.9 <= values["noise_match"] <= 1.1


def test_aspect_drift_detects_reframing(tmp_path):
    a = _save(tmp_path, "a.jpg", Image.new("RGB", (600, 800), (120, 110, 100)))
    b = _save(tmp_path, "b.jpg", Image.new("RGB", (800, 800), (120, 110, 100)))
    assert metrics.aspect_drift(a, b) > 0.10  # 3:4 -> 1:1 must flag


def test_brightness_drift_detects_dark_render(tmp_path):
    base = Image.effect_noise((400, 300), 20).convert("RGB")
    dark = base.point(lambda v: max(0, v - 60))
    a = _save(tmp_path, "a.jpg", base)
    b = _save(tmp_path, "b.jpg", dark)
    values, flags = metrics.evaluate_case(a, b, is_clothing=False)
    assert values["brightness_drift"] < -40
    assert any("brightness_drift" in f for f in flags)


def test_noise_match_detects_denoised_output(tmp_path):
    noisy = Image.effect_noise((400, 300), 50).convert("RGB")
    clean = noisy.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(3))
    a = _save(tmp_path, "a.jpg", noisy)
    b = _save(tmp_path, "b.jpg", clean)
    assert metrics.noise_match(a, b) < 0.75  # AI-gloss must flag


def test_lower_skin_ratio_detects_leg_erasure(tmp_path):
    skin, fabric = (210, 160, 130), (20, 90, 60)
    base = Image.new("RGB", (300, 600), (200, 200, 200))
    with_legs = base.copy()
    with_legs.paste(skin, (100, 420, 200, 600))     # legs in the lower band
    covered = base.copy()
    covered.paste(fabric, (100, 420, 200, 600))     # fabric where legs were
    a = _save(tmp_path, "a.jpg", with_legs)
    b = _save(tmp_path, "b.jpg", covered)
    ratio = metrics.lower_skin_ratio(a, b)
    assert ratio < 0.5
    values, flags = metrics.evaluate_case(a, b, is_clothing=True)
    assert any("lower_skin_ratio" in f for f in flags)


def test_preserved_region_parity_ignores_the_edit(tmp_path):
    """A high-detail garment pasted into one region must NOT make the preserved
    region's noise/sharpness parity flag: parity is measured off-edit."""
    base = Image.effect_noise((400, 600), 22).convert("RGB")
    edited = base.copy()
    # paste a high-frequency 'patterned garment' over the torso band
    patch = Image.effect_noise((200, 220), 90).convert("RGB")
    edited.paste(patch, (100, 120))
    a = _save(tmp_path, "a.jpg", base)
    b = _save(tmp_path, "b.jpg", edited)
    # The global sharpness ratio is inflated by the busy patch...
    assert metrics.sharpness_match(a, b) > 1.2
    # ...but the preserved region is unchanged, so its parity stays ~1.0.
    pr = metrics.preserved_region_parity(a, b)
    assert 0.85 <= pr["noise_preserved"] <= 1.15
    assert 0.85 <= pr["sharpness_preserved"] <= 1.15
    assert pr["edit_fraction"] > 0.02


def test_change_fraction_and_mean_abs_diff_measure_locality(tmp_path):
    base = Image.effect_noise((400, 300), 24).convert("RGB")
    edited = base.copy()
    edited.paste((220, 40, 40), (180, 120, 230, 180))  # a small local edit
    a = _save(tmp_path, "a.jpg", base)
    b = _save(tmp_path, "b.jpg", edited)
    # Identical images: ~no change, tiny mean diff.
    assert metrics.change_fraction(a, a) < 0.01
    assert metrics.mean_abs_diff(a, a) < 2.0
    # A small painted block: a small but non-zero changed fraction.
    cf = metrics.change_fraction(a, b)
    assert 0.005 < cf < 0.20
    assert metrics.mean_abs_diff(a, b) > metrics.mean_abs_diff(a, a)
