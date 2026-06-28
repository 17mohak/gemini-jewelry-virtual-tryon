"""Local image-quality heuristics for the try-on evaluation harness.

Pillow-only (no extra dependencies, no network, no API spend). These metrics
are deliberately humble: they are REGRESSION DETECTORS, not absolute quality
judges. A flagged metric means "a human should look at this output"; clean
metrics do not certify photorealism. Final judgement is the human rubric in
the generated report.

Metric overview
---------------
aspect_drift           framing stability (audit failure FM-7)
border_preservation    background drift outside the edit region (FM-2/FM-4)
noise_match            sensor-noise / grain parity, output vs input (FM-2/FM-8)
sharpness_match        sharpness-profile parity (FM-2/FM-8)
lower_skin_ratio       visible-skin conservation in the lower body (FM-4),
                       clothing cases only
brightness_drift       global exposure drift (the dark-render failure, FM-2)
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat

ANALYSIS_SIZE = 512  # all comparisons run on bounded copies for speed


def _load(path: Path, size: int = ANALYSIS_SIZE) -> Image.Image:
    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size))
    return im


def aspect_drift(input_path: Path, output_path: Path) -> float:
    """|log(output ratio / input ratio)| — 0.0 means identical framing shape.

    Values above ~0.10 mean a visibly different crop (e.g. 3:4 vs 4:5 is
    ~0.07; 3:4 vs 1:1 is ~0.29).
    """
    with Image.open(input_path) as a, Image.open(output_path) as b:
        ra = a.width / a.height
        rb = b.width / b.height
    return abs(math.log(rb / ra))


def border_preservation(input_path: Path, output_path: Path) -> float:
    """Mean absolute pixel difference (0-255) in the outer 10% border strips.

    The edit region (jewelry/garment) is normally central, so heavy change in
    the border indicates background drift or re-framing. Below ~12 is normal
    (re-encode noise); above ~30 deserves human review.
    """
    a = _load(input_path)
    b = _load(output_path).resize(a.size)
    diff = ImageChops.difference(a.convert("L"), b.convert("L"))
    w, h = diff.size
    bw, bh = max(1, w // 10), max(1, h // 10)
    strips = [
        diff.crop((0, 0, w, bh)),          # top
        diff.crop((0, h - bh, w, h)),      # bottom
        diff.crop((0, 0, bw, h)),          # left
        diff.crop((w - bw, 0, w, h)),      # right
    ]
    total = sum(ImageStat.Stat(s).mean[0] * (s.width * s.height) for s in strips)
    area = sum(s.width * s.height for s in strips)
    return total / area


def _high_pass_energy(im: Image.Image) -> float:
    """Stddev of the edge-filtered luma — a proxy for grain + fine detail."""
    edges = im.convert("L").filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges).stddev[0]


def noise_match(input_path: Path, output_path: Path) -> float:
    """Output/input high-frequency energy ratio. 1.0 = same grain character.

    Below ~0.75 the output is noticeably cleaner/denoised than the input
    (the 'AI gloss' failure); above ~1.3 it is artificially crunchy.
    """
    a, b = _load(input_path), _load(output_path)
    ea, eb = _high_pass_energy(a), _high_pass_energy(b)
    return eb / ea if ea > 0 else 1.0


def sharpness_match(input_path: Path, output_path: Path) -> float:
    """Output/input mean edge magnitude ratio. 1.0 = same sharpness profile."""
    a, b = _load(input_path), _load(output_path)
    ea = ImageStat.Stat(a.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]
    eb = ImageStat.Stat(b.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]
    return eb / ea if ea > 0 else 1.0


def _skin_fraction(im: Image.Image) -> float:
    """Fraction of pixels matching a permissive RGB skin heuristic.

    Classic rule-based skin mask (Peer et al. style): generous on purpose —
    we compare the SAME heuristic between input and output, so systematic
    bias cancels out.
    """
    pixels = im.getdata()
    skin = 0
    for r, g, b in pixels:
        if (
            r > 95 and g > 40 and b > 20
            and (max(r, g, b) - min(r, g, b)) > 15
            and abs(r - g) > 15 and r > g and r > b
        ):
            skin += 1
    return skin / max(1, len(pixels))


def lower_skin_ratio(input_path: Path, output_path: Path) -> float:
    """Output/input visible-skin fraction in the lower 35% of the frame.

    Detects the leg-erasure failure: a garment lengthened over the legs
    drops this ratio sharply. ~1.0 = legs as visible as before; below ~0.5
    means visible lower-body skin was halved -> human review. Only
    meaningful for clothing (full-body) cases.
    """
    a, b = _load(input_path), _load(output_path).resize(_load(input_path).size)
    h = a.height
    band = (0, int(h * 0.65), a.width, h)
    fa, fb = _skin_fraction(a.crop(band)), _skin_fraction(b.crop(band))
    if fa < 0.01:  # no measurable skin in the input band; metric not applicable
        return 1.0
    return fb / fa


def brightness_drift(input_path: Path, output_path: Path) -> float:
    """Mean-luma difference (output - input), in 0-255 units.

    Catches the global exposure failures (a -40 darkening was observed in
    the audit). |drift| above ~15 deserves human review.
    """
    a, b = _load(input_path), _load(output_path)
    la = ImageStat.Stat(a.convert("L")).mean[0]
    lb = ImageStat.Stat(b.convert("L")).mean[0]
    return lb - la


def mean_abs_diff(input_path: Path, output_path: Path) -> float:
    """Global mean absolute pixel difference (0-255) over the whole frame.

    A blunt overall-change measure. For a pixel-preserving composite this drops
    sharply versus the raw model output, because everything outside the edit
    region is restored to the original.
    """
    a = _load(input_path)
    b = _load(output_path).resize(a.size)
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def change_fraction(
    input_path: Path, output_path: Path, threshold: int = 25
) -> float:
    """Fraction of pixels whose luma changed by more than ``threshold``.

    Approximates the size of the genuinely edited region. Lower is better for a
    pixel-preserving pipeline: it means fewer original pixels were disturbed.
    """
    a = _load(input_path).convert("L")
    b = _load(output_path).resize(a.size).convert("L")
    diff = ImageChops.difference(a, b)
    hist = diff.histogram()
    changed = sum(hist[threshold + 1:])
    return changed / max(1, sum(hist))


# ── Thresholds & scoring ─────────────────────────────────────────────────────

THRESHOLDS = {
    "aspect_drift": ("max", 0.10),
    "border_preservation": ("max", 30.0),
    "noise_match": ("range", (0.75, 1.30)),
    "sharpness_match": ("range", (0.70, 1.40)),
    "lower_skin_ratio": ("min", 0.50),
    "brightness_drift": ("abs_max", 15.0),
}


def evaluate_case(
    input_path: Path, output_path: Path, *, is_clothing: bool
) -> tuple[dict[str, float], list[str]]:
    """Compute all applicable metrics and return ``(values, flags)``."""
    values: dict[str, float] = {
        "aspect_drift": round(aspect_drift(input_path, output_path), 4),
        "border_preservation": round(border_preservation(input_path, output_path), 2),
        "noise_match": round(noise_match(input_path, output_path), 3),
        "sharpness_match": round(sharpness_match(input_path, output_path), 3),
        "brightness_drift": round(brightness_drift(input_path, output_path), 2),
    }
    if is_clothing:
        values["lower_skin_ratio"] = round(
            lower_skin_ratio(input_path, output_path), 3
        )

    flags: list[str] = []
    for name, value in values.items():
        kind, limit = THRESHOLDS[name]
        if kind == "max" and value > limit:
            flags.append(f"{name}={value} exceeds {limit}")
        elif kind == "min" and value < limit:
            flags.append(f"{name}={value} below {limit}")
        elif kind == "abs_max" and abs(value) > limit:
            flags.append(f"{name}={value} outside +/-{limit}")
        elif kind == "range" and not (limit[0] <= value <= limit[1]):
            flags.append(f"{name}={value} outside {limit}")
    return values, flags
