"""Adversarial garment stress evaluation for the clothing try-on pipeline.

Runs the FULL shipped pipeline (prompt builder -> Nano Banana -> pixel-
preserving compositing) on the hard garment set described in
``eval/stress_manifest.json`` and produces, per garment, a comparison panel
plus objective metrics, so weaknesses can be found by zooming into pixels.

The garment images live in ``eval/stress/refs/`` (gitignored, user-supplied);
they are treated as adversarial stress assets, NOT catalog items.

Usage (NANOBANANA_API_KEY must be valid for live runs):

    python eval/stress_eval.py --dry-run            # build prompts only, no API
    python eval/stress_eval.py --ids ref_03,ref_13  # a subset
    python eval/stress_eval.py --all                # the whole set
    python eval/stress_eval.py --all --raw          # skip compositing (A/B)

Each run writes to ``eval/stress/runs/<UTC stamp>/``:
  - <id>_raw.png / <id>_composite.jpg
  - <id>_panel.jpg   : person | garment | raw | composite | diff(composite)
  - report.json / report.md

Cost: IMAGE generation only. Never calls the video API.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import clothing_prompt_builder as CPB  # noqa: E402
from backend.services import compositing as C  # noqa: E402
from backend.services import nanobanana_service as NB  # noqa: E402
from eval import metrics as M  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
STRESS_DIR = EVAL_DIR / "stress"
REFS_DIR = STRESS_DIR / "refs"
RUNS_DIR = STRESS_DIR / "runs"
MANIFEST = EVAL_DIR / "stress_manifest.json"

PANEL_H = 460


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def select(man: dict, args: argparse.Namespace) -> list[dict]:
    items = man["items"]
    if args.ids:
        want = {x.strip() for x in args.ids.split(",")}
        items = [it for it in items if it["id"] in want]
    return items


def _tile(im: Image.Image, label: str) -> Image.Image:
    w = max(1, round(im.width * PANEL_H / im.height))
    t = im.convert("RGB").resize((w, PANEL_H), Image.LANCZOS)
    band = Image.new("RGB", (w, 22), (20, 20, 20))
    ImageDraw.Draw(band).text((6, 6), label, fill=(245, 245, 245))
    out = Image.new("RGB", (w, PANEL_H + 22), (20, 20, 20))
    out.paste(band, (0, 0)); out.paste(t, (0, 22))
    return out


def _heat(diff: np.ndarray) -> Image.Image:
    d = np.clip(diff / 60.0, 0, 1)
    rgb = (np.stack([np.clip(1.5 * d, 0, 1),
                     np.clip(1.5 * d - 0.5, 0, 1),
                     np.clip(2.0 * d - 1.0, 0, 1)], -1) * 255).astype(np.uint8)
    return Image.fromarray(rgb)


def build_panel(person: Path, garment: Path, raw: Image.Image,
                comp: Image.Image) -> Image.Image:
    base = Image.open(person).convert("RGB")
    raw_r = raw.convert("RGB").resize(base.size)
    comp_r = comp.convert("RGB").resize(base.size)
    diff = _heat(np.abs(np.asarray(base, np.float32) - np.asarray(comp_r, np.float32)).mean(-1))
    tiles = [
        _tile(base, "1 person"),
        _tile(Image.open(garment), "2 garment ref"),
        _tile(raw_r, "3 raw model"),
        _tile(comp_r, "4 composite"),
        _tile(diff, "5 diff: person vs composite"),
    ]
    gap = 6
    W = sum(t.width for t in tiles) + gap * (len(tiles) - 1)
    panel = Image.new("RGB", (W, tiles[0].height), (20, 20, 20))
    x = 0
    for t in tiles:
        panel.paste(t, (x, 0)); x += t.width + gap
    return panel


def run(args: argparse.Namespace) -> int:
    man = load_manifest()
    person = ROOT / man["base_person"]
    items = select(man, args)
    if not items:
        print("No items selected."); return 1
    if not person.exists():
        raise SystemExit(f"Base person photo missing: {person}")

    print(f"{len(items)} garment(s): {', '.join(it['id'] for it in items)}")
    if args.dry_run:
        for it in items:
            prompt = CPB.build_clothing_tryon_prompt(it)
            physics = CPB.material_guidance(it)
            print(f"  {it['id']:7s} type={it['type']:8s} layer={it.get('layer','replace'):7s} "
                  f"prompt_chars={len(prompt)} material_snippets={len(physics)}")
        print("Dry run complete - no API calls made.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = RUNS_DIR / stamp
    out_dir.mkdir(parents=True)
    results = []
    for i, it in enumerate(items):
        garment = REFS_DIR / it["file"]
        if not garment.exists():
            print(f"  SKIP {it['id']}: missing {garment}"); continue
        prompt = CPB.build_clothing_tryon_prompt(it)
        print(f"[{i+1}/{len(items)}] {it['id']} ({it['type']}) ...", flush=True)
        rec = {"id": it["id"], "name": it["name"], "type": it["type"],
               "difficulty": it.get("difficulty"), "predicted": it.get("predicted_failures", [])}
        try:
            img, mime = NB.generate_tryon_image(person, garment, prompt)
        except NB.NanoBananaError as exc:
            rec.update(status="generation_failed", error=str(exc))
            results.append(rec); print(f"    FAILED: {exc}"); continue

        raw_im = Image.open(__import__("io").BytesIO(img)).convert("RGB")
        (out_dir / f"{it['id']}_raw.png").write_bytes(img)

        if args.raw:
            comp_im = raw_im; applied = False; edit_frac = 1.0
        else:
            res = C.composite_bytes(person, img)
            comp_im = res.image; applied = res.applied; edit_frac = res.edit_fraction
        comp_path = out_dir / f"{it['id']}_composite.jpg"
        comp_im.convert("RGB").save(comp_path, "JPEG", quality=95)

        panel = build_panel(person, garment, raw_im, comp_im)
        panel.save(out_dir / f"{it['id']}_panel.jpg", quality=90)

        values, flags = M.evaluate_case(person, comp_path, is_clothing=True)
        # Edit-region-aware parity: did the model disturb grain/sharpness of the
        # PRESERVED (non-garment) pixels? Global noise/sharp over-flag patterned
        # garments, so this is the meaningful signal for the stress set.
        parity = M.preserved_region_parity(person, comp_path)
        rec.update(status="ok", composited=applied, edit_fraction=round(edit_frac, 4),
                   metrics=values, parity=parity, flags=flags)
        results.append(rec)
        print(f"    ok edit={edit_frac:.3f} preserved(noise={parity['noise_preserved']},"
              f"sharp={parity['sharpness_preserved']}) flags={flags or '-'}")
        if i + 1 < len(items):
            time.sleep(args.delay)

    (out_dir / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(_report_md(stamp, results), encoding="utf-8")
    print(f"\nReport: {(out_dir / 'report.md').relative_to(ROOT)}")
    return 0


def _report_md(stamp: str, results: list[dict]) -> str:
    L = [f"# Adversarial stress run {stamp}", "",
         "Full pipeline (prompt v3 + compositing) on the hard garment set. "
         "Inspect panels at pixel level; metrics only flag for human review.", "",
         "| id | type | diff | edit | preserved noise/sharp | flags |",
         "| --- | --- | --- | --- | --- | --- |"]
    for r in results:
        if r["status"] != "ok":
            L.append(f"| {r['id']} | {r['type']} | {r.get('difficulty','')} | FAILED | - | {r.get('error','')[:50]} |")
            continue
        p = r.get("parity", {})
        L.append(f"| {r['id']} | {r['type']} | {r.get('difficulty','')} | "
                 f"{r['edit_fraction']:.2f} | {p.get('noise_preserved','-')}/{p.get('sharpness_preserved','-')} "
                 f"| {'; '.join(r['flags']) if r['flags'] else '-'} |")
    L += ["", "## Panels", ""]
    for r in results:
        if r["status"] == "ok":
            L += [f"### {r['id']} — {r['name']}", "", f"![panel]({r['id']}_panel.jpg)", ""]
    return "\n".join(L)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="run every garment in the manifest")
    g.add_argument("--ids", help="comma-separated garment ids (e.g. ref_03,ref_13)")
    p.add_argument("--dry-run", action="store_true", help="build prompts only, no API calls")
    p.add_argument("--raw", action="store_true", help="skip compositing (score raw model output)")
    p.add_argument("--delay", type=float, default=8.0, help="seconds between generations")
    raise SystemExit(run(p.parse_args()))


if __name__ == "__main__":
    main()
