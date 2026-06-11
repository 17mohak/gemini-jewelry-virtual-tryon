"""Try-on evaluation harness: generate benchmark cases, score, and report.

Usage (from the repo root, with NANOBANANA_API_KEY in .env):

    python eval/run_eval.py --hard          # the 6 hard regression cases
    python eval/run_eval.py --all           # full catalog sweep (15 cases)
    python eval/run_eval.py --cases id1,id2 # specific cases
    python eval/run_eval.py --dry-run --all # validate definitions, no API calls

Outputs land in ``eval/runs/<UTC timestamp>/``:
  - one generated image per case
  - report.json (machine-readable metrics + flags)
  - report.md   (human-readable table with a rubric column to fill in)

Outputs whose heuristics raise flags are also copied into ``eval/failures/``
so the failure gallery accumulates real evidence over time.

Cost notes: IMAGE generation only (free-tier Nano Banana). This harness never
touches the video API.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import CATALOG_DIR  # noqa: E402
from backend.services import (  # noqa: E402
    clothing_prompt_builder,
    nanobanana_service,
    prompt_builder,
)

EVAL_DIR = Path(__file__).resolve().parent
RUNS_DIR = EVAL_DIR / "runs"
FAILURES_DIR = EVAL_DIR / "failures"

RUBRIC = (
    "fidelity /5, identity /5, integration /5, lighting /5, placement /5"
)


def load_catalogs() -> dict[str, tuple[dict, str]]:
    items: dict[str, tuple[dict, str]] = {}
    for filename, category in (("catalog.json", "jewelry"), ("clothing.json", "clothing")):
        data = json.loads((CATALOG_DIR / filename).read_text(encoding="utf-8"))
        for item in data["items"]:
            items[item["id"]] = (item, category)
    return items


def load_benchmark() -> dict:
    return json.loads((EVAL_DIR / "benchmark.json").read_text(encoding="utf-8"))


def build_prompt(item: dict, category: str) -> str:
    if category == "jewelry":
        return prompt_builder.build_tryon_prompt(item)
    return clothing_prompt_builder.build_clothing_tryon_prompt(item)


def select_cases(bench: dict, args: argparse.Namespace) -> list[dict]:
    cases = bench["cases"]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"Unknown case id(s): {', '.join(sorted(unknown))}")
        return [c for c in cases if c["id"] in wanted]
    if args.all:
        return cases
    return [c for c in cases if c.get("hard")]


def run(args: argparse.Namespace) -> int:
    bench = load_benchmark()
    catalog = load_catalogs()
    cases = select_cases(bench, args)
    inputs = {k: ROOT / v for k, v in bench["inputs"].items()}

    # Validate every selected case before spending anything.
    for case in cases:
        item, category = catalog[case["item_id"]]
        kind = (
            prompt_builder.required_photo_kind(item["type"])
            if category == "jewelry"
            else clothing_prompt_builder.required_photo_kind(item["type"])
        )
        case["_item"], case["_category"], case["_kind"] = item, category, kind
        if not inputs[kind].exists():
            raise SystemExit(f"Missing benchmark input photo: {inputs[kind]}")
        if not (CATALOG_DIR / item["image"]).exists():
            raise SystemExit(f"Missing product image for {item['id']}")

    print(f"{len(cases)} case(s) selected: {', '.join(c['id'] for c in cases)}")
    if args.dry_run:
        for case in cases:
            prompt = build_prompt(case["_item"], case["_category"])
            print(f"  {case['id']}: kind={case['_kind']} prompt_chars={len(prompt)}")
        print("Dry run complete - no API calls made.")
        return 0

    from eval.metrics import evaluate_case  # deferred: not needed for dry runs

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / stamp
    run_dir.mkdir(parents=True)
    FAILURES_DIR.mkdir(exist_ok=True)

    results = []
    for i, case in enumerate(cases):
        item, category, kind = case["_item"], case["_category"], case["_kind"]
        input_path = inputs[kind]
        prompt = build_prompt(item, category)
        print(f"[{i + 1}/{len(cases)}] {case['id']} ({category}/{item['type']}) ...", flush=True)
        record = {
            "case": case["id"],
            "item": item["name"],
            "category": category,
            "type": item["type"],
            "input": str(input_path.relative_to(ROOT)),
            "hard": case.get("hard", False),
            "notes": case.get("notes", ""),
        }
        try:
            image, mime = nanobanana_service.generate_tryon_image(
                input_path, CATALOG_DIR / item["image"], prompt
            )
        except nanobanana_service.NanoBananaError as exc:
            record.update(status="generation_failed", error=str(exc))
            results.append(record)
            print(f"    FAILED: {exc}")
            continue

        ext = "png" if "png" in mime else "jpg"
        out_path = run_dir / f"{case['id']}.{ext}"
        out_path.write_bytes(image)

        values, flags = evaluate_case(
            input_path, out_path, is_clothing=(category == "clothing")
        )
        record.update(
            status="ok",
            output=out_path.name,
            metrics=values,
            flags=flags,
            human_rubric=None,  # to be filled in during review
        )
        results.append(record)
        if flags:
            flagged = FAILURES_DIR / f"{stamp}_{out_path.name}"
            shutil.copyfile(out_path, flagged)
            print(f"    FLAGGED ({len(flags)}): {'; '.join(flags)}")
            print(f"    copied to {flagged.relative_to(ROOT)}")
        else:
            print(f"    ok  {values}")
        if i + 1 < len(cases):
            time.sleep(args.delay)

    (run_dir / "report.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    (run_dir / "report.md").write_text(_markdown_report(stamp, results), encoding="utf-8")
    print(f"\nReports written to {run_dir.relative_to(ROOT)}")
    flagged_count = sum(1 for r in results if r.get("flags"))
    failed_count = sum(1 for r in results if r["status"] != "ok")
    print(f"Summary: {len(results)} cases, {failed_count} failed, {flagged_count} flagged for review.")
    return 1 if failed_count else 0


def _markdown_report(stamp: str, results: list[dict]) -> str:
    lines = [
        f"# Evaluation run {stamp}",
        "",
        "Heuristic metrics flag outputs for human review; they do not certify",
        "quality. Fill the human rubric column while inspecting each image:",
        f"`{RUBRIC}`.",
        "",
        "| case | type | status | aspect | border | noise | sharp | bright | skin | flags | human rubric |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if r["status"] != "ok":
            lines.append(
                f"| {r['case']} | {r['type']} | FAILED: {r.get('error', '')[:60]} "
                "| - | - | - | - | - | - | - | - |"
            )
            continue
        m = r["metrics"]
        lines.append(
            "| {case} | {type} | ok | {aspect} | {border} | {noise} | {sharp} | {bright} | {skin} | {flags} | _to fill_ |".format(
                case=r["case"],
                type=r["type"],
                aspect=m["aspect_drift"],
                border=m["border_preservation"],
                noise=m["noise_match"],
                sharp=m["sharpness_match"],
                bright=m["brightness_drift"],
                skin=m.get("lower_skin_ratio", "n/a"),
                flags="; ".join(r["flags"]) if r["flags"] else "-",
            )
        )
    lines += [
        "",
        "Threshold reference: aspect_drift<=0.10, border<=30, noise 0.75-1.30, "
        "sharpness 0.70-1.40, |brightness|<=15, lower_skin_ratio>=0.50.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--hard", action="store_true", help="run the hard regression subset (default)")
    group.add_argument("--all", action="store_true", help="run every benchmark case")
    group.add_argument("--cases", help="comma-separated case ids")
    parser.add_argument("--dry-run", action="store_true", help="validate without API calls")
    parser.add_argument("--delay", type=float, default=8.0, help="seconds between generations (rate-limit kindness)")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
