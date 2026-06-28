"""Offline A/B validation for the pixel-preserving compositing stage.

This harness spends **no API quota**: it runs the compositing post-process
(``backend/services/compositing.py``) on *already-generated* try-on images that
are committed to the repo, and measures whether compositing makes each output
objectively closer to a real photograph of the input person.

For every (input photo, raw model output) pair it:

  1. runs the composite,
  2. computes the local image-quality metrics (``eval/metrics.py``) for the raw
     output vs input AND the composite vs input,
  3. writes a side-by-side panel:
     ``[ input | raw model | composite | edit alpha | diff(raw) | diff(comp) ]``
     so a human can see exactly which pixels changed, and
  4. emits ``report.md`` / ``report.json`` with the before/after metric deltas.

The thesis being tested (see ``eval/REALISM_AUDIT.md``): because the model
re-synthesizes the whole frame, the raw output drifts in exposure, grain and
background everywhere; compositing restores the original pixels outside a tight
edit region, so background drift and global brightness drift collapse toward
zero while the jewelry/garment itself is preserved.

Usage::

    python eval/compositing_eval.py            # all committed pairs
    python eval/compositing_eval.py --open      # also print the report path

Outputs land in ``eval/compositing/<UTC timestamp>/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import compositing as C  # noqa: E402
from eval import metrics as M  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
OUT_ROOT = EVAL_DIR / "compositing"

PANEL_H = 360  # px height each tile is scaled to in the panel


def discover_pairs() -> list[dict]:
    """Committed (input, raw-output) pairs that share the input's framing.

    Only aspect-aligned pairs are usable: a composite assumes the model kept
    the input's crop (true for everything generated after aspect pinning).
    """
    demo = ROOT / "docs" / "demo"
    pairs = [
        # (input, raw output, category, item_type)
        (demo / "input_face.jpg", demo / "result_earrings_v2.jpg", "jewelry", "earrings"),
        (demo / "input_body.jpg", demo / "result_breton_top.jpg", "clothing", "top"),
        (demo / "input_body.jpg", demo / "result_wrap_dress_v2.jpg", "clothing", "dress"),
    ]
    # Pull in the latest benchmark sweep (aspect-pinned synthetic people).
    runs = sorted((EVAL_DIR / "runs").glob("*/"))
    if runs:
        run = runs[-1]
        bench = {
            "necklace-cross-pendant": ("input_face.jpg", "jewelry", "necklace"),
            "earrings-gold-drop": ("input_face.jpg", "jewelry", "earrings"),
            "ring-three-stone-diamond": ("input_hand.jpg", "jewelry", "ring"),
            "bracelet-enamel-bangle": ("input_hand.jpg", "jewelry", "bracelet"),
            "clothing-breton-top": ("input_body.jpg", "clothing", "top"),
            "clothing-green-wrap-dress": ("input_body.jpg", "clothing", "dress"),
        }
        for case, (inp, cat, typ) in bench.items():
            out = run / f"{case}.jpg"
            if out.exists():
                pairs.append((demo / inp, out, cat, typ))

    records = []
    for inp, out, cat, typ in pairs:
        if inp.exists() and out.exists():
            records.append({
                "name": out.stem, "input": inp, "output": out,
                "category": cat, "type": typ,
            })
    return records


def _heat(diff: np.ndarray) -> Image.Image:
    """Grayscale->magma-ish heatmap of a per-pixel diff (0-255 input)."""
    d = np.clip(diff / 60.0, 0, 1)  # saturate at deltaE-ish 60 for contrast
    r = np.clip(1.5 * d, 0, 1)
    g = np.clip(1.5 * d - 0.5, 0, 1)
    b = np.clip(2.0 * d - 1.0, 0, 1)
    rgb = (np.stack([r, g, b], -1) * 255).astype(np.uint8)
    return Image.fromarray(rgb)


def _tile(im: Image.Image, label: str) -> Image.Image:
    from PIL import ImageDraw
    w = round(im.width * PANEL_H / im.height)
    t = im.convert("RGB").resize((w, PANEL_H), Image.LANCZOS)
    band = Image.new("RGB", (w, 22), (20, 20, 20))
    ImageDraw.Draw(band).text((6, 5), label, fill=(240, 240, 240))
    out = Image.new("RGB", (w, PANEL_H + 22), (20, 20, 20))
    out.paste(band, (0, 0)); out.paste(t, (0, 22))
    return out


def build_panel(rec: dict, composite: Image.Image) -> Image.Image:
    inp = Image.open(rec["input"]).convert("RGB")
    raw = Image.open(rec["output"]).convert("RGB").resize(inp.size)
    comp = composite.convert("RGB").resize(inp.size)
    ia, ra, ca = (np.asarray(x, np.float32) for x in (inp, raw, comp))
    diff_raw = _heat(np.abs(ia - ra).mean(-1))
    diff_comp = _heat(np.abs(ia - ca).mean(-1))
    tiles = [
        _tile(inp, "1 input"),
        _tile(raw, "2 raw model output"),
        _tile(comp, "3 composite"),
        _tile(diff_raw, "4 diff: input vs raw"),
        _tile(diff_comp, "5 diff: input vs composite"),
    ]
    gap = 6
    W = sum(t.width for t in tiles) + gap * (len(tiles) - 1)
    panel = Image.new("RGB", (W, tiles[0].height), (20, 20, 20))
    x = 0
    for t in tiles:
        panel.paste(t, (x, 0)); x += t.width + gap
    return panel


def metric_row(input_path: Path, output_path: Path, is_clothing: bool) -> dict:
    values, _flags = M.evaluate_case(input_path, output_path, is_clothing=is_clothing)
    values["mean_abs_diff"] = round(M.mean_abs_diff(input_path, output_path), 2)
    values["change_fraction"] = round(M.change_fraction(input_path, output_path), 4)
    return values


def run(args: argparse.Namespace) -> int:
    pairs = discover_pairs()
    if not pairs:
        print("No committed input/output pairs found.")
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / stamp
    out_dir.mkdir(parents=True)

    results = []
    for rec in pairs:
        res = C.composite_bytes(rec["input"], rec["output"].read_bytes())
        comp_path = out_dir / f"{rec['name']}_composite.jpg"
        res.image.convert("RGB").save(comp_path, "JPEG", quality=95)
        panel = build_panel(rec, res.image)
        panel_path = out_dir / f"{rec['name']}_panel.jpg"
        panel.save(panel_path, "JPEG", quality=90)

        is_cloth = rec["category"] == "clothing"
        before = metric_row(rec["input"], rec["output"], is_cloth)
        after = metric_row(rec["input"], comp_path, is_cloth)
        results.append({
            "name": rec["name"], "type": rec["type"],
            "edit_fraction": round(res.edit_fraction, 4), "applied": res.applied,
            "before": before, "after": after,
            "panel": panel_path.name, "composite": comp_path.name,
        })
        print(f"{rec['name']:30s} edit={res.edit_fraction:.3f} "
              f"applied={res.applied}")
        print(f"   border {before['border_preservation']:6.2f} -> {after['border_preservation']:6.2f}   "
              f"bright {before['brightness_drift']:+6.2f} -> {after['brightness_drift']:+6.2f}   "
              f"meanΔ {before['mean_abs_diff']:6.2f} -> {after['mean_abs_diff']:6.2f}")

    (out_dir / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(_report_md(stamp, results), encoding="utf-8")
    print(f"\nReport: {(out_dir / 'report.md').relative_to(ROOT)}")
    return 0


def _report_md(stamp: str, results: list[dict]) -> str:
    L = [
        f"# Compositing A/B — {stamp}",
        "",
        "Pixel-preserving compositing applied to committed model outputs. "
        "No API spend. Lower `border` and `|bright|` and `meanΔ` are better "
        "(closer to the original photo outside the edit); `edit` is the "
        "fraction of pixels taken from the model.",
        "",
        "| case | edit | border (raw→comp) | bright (raw→comp) | meanΔ (raw→comp) | noise (raw→comp) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        b, a = r["before"], r["after"]
        L.append(
            f"| {r['name']} | {r['edit_fraction']:.1%} "
            f"| {b['border_preservation']:.2f} → **{a['border_preservation']:.2f}** "
            f"| {b['brightness_drift']:+.2f} → **{a['brightness_drift']:+.2f}** "
            f"| {b['mean_abs_diff']:.2f} → **{a['mean_abs_diff']:.2f}** "
            f"| {b['noise_match']:.2f} → {a['noise_match']:.2f} |"
        )
    L += ["", "## Panels", ""]
    for r in results:
        L += [f"### {r['name']}", "", f"![panel]({r['panel']})", ""]
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--open", action="store_true", help="print the report path at the end")
    raise SystemExit(run(p.parse_args()))


if __name__ == "__main__":
    main()
