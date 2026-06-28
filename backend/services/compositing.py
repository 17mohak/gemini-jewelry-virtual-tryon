"""Pixel-preserving compositing for virtual try-on.

Why this module exists
----------------------
Nano Banana (like every diffusion image-editing model) *re-synthesizes the
whole image*. Even with a perfect prompt, the returned image is a fresh
rendering of the scene: the face is re-drawn, the background is re-encoded, the
grain is smoothed, the exposure drifts a couple of stops. The realism audit
(``eval/REALISM_AUDIT.md``) traced almost every remaining defect — loss of
facial texture, identity drift, "AI gloss", composited-looking jewelry,
brightness/white-balance drift, background drift — back to this single cause:
**global re-synthesis**. Prompt engineering cannot fix it, because the model
has no mechanism to return the original pixels untouched.

This module fixes it the way a compositing artist would: keep the model's
output ONLY where the image actually changed (the jewelry/garment and its
contact shadows), and restore the *original photograph's pixels everywhere
else*. The face, hair, skin texture, background and film grain that the user
uploaded are carried through byte-for-byte outside a tight, feathered edit
region.

Empirically (see ``eval/compositing_eval.py``) the aspect-pinned model output
is already near-perfectly registered with the input — median per-pixel
difference is at the JPEG-recompression floor — so a plain resize aligns the
two and a difference mask isolates the edit cleanly. No optical-flow or ECC
registration is required.

Pipeline (all numpy / scipy / Pillow — no heavy CV dependency)
-------------------------------------------------------------
1. Resize the model output onto the original photo's pixel grid.
2. **Global tone harmonization**: fit a per-channel linear map (gain + bias)
   on the unchanged majority of pixels so the output's exposure/white balance
   matches the input. This removes the global re-grade *and* means the seam
   between kept-original and kept-model pixels has no tonal step.
3. **Change-mask extraction**: perceptual (CIELAB) difference -> blur ->
   threshold -> remove specks -> fill holes -> dilate to catch contact
   shadows. This is the region the model legitimately changed.
4. **Feather** the mask into a soft alpha for a seamless boundary.
5. **Grain match**: re-inject sensor noise into the (denoised) edit region so
   its grain matches the surrounding original photo.
6. Alpha-composite: ``original * (1 - a) + harmonized_model * a``.

A safety valve returns the raw model output unchanged when the mask is empty
or implausibly large (so the post-process can never make things worse than the
baseline it replaces).

Identity preservation is a *consequence* of step 3, not a separate stage: the
face lies outside the change mask, so its pixels are the literal original — no
identity drift is possible there. An earlier iteration added an explicit
elliptical "face-lock" ROI; offline validation (``eval/compositing_eval.py``)
showed it clipped earrings and necklaces that sit close to a small face while
adding nothing the threshold mask did not already provide, so it was removed.
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

logger = logging.getLogger("services.compositing")


# ── Tunables ──────────────────────────────────────────────────────────────────
# Defaults were tuned on the committed input/output pairs (see
# eval/compositing_eval.py). They are deliberately conservative: when in doubt
# the pipeline keeps MORE of the model output, never less, so a mis-tuned mask
# degrades gracefully toward the raw-output baseline.

@dataclass(frozen=True)
class CompositeConfig:
    work_size: int = 1024          # cap on the long edge during processing
    delta_e_threshold: float = 9.0  # CIELAB distance that counts as "changed"
    texture_threshold: float = 3.0  # local-texture-stddev change that counts as "changed"
    blur_sigma: float = 1.5        # pre-threshold smoothing of the diff map
    min_region_frac: float = 0.0008  # drop connected changes smaller than this
    dilate_px: int = 6             # grow mask to include contact shadows
    feather_px: float = 4.0        # gaussian feather of the alpha boundary
    max_edit_frac: float = 0.75    # bail to raw output above this changed area
    grain_strength: float = 0.8    # 0 disables grain match; 1 = full match
    tone_harmonize: bool = True


DEFAULT_CONFIG = CompositeConfig()


# ── Color science (vectorized sRGB <-> CIELAB, D65) ──────────────────────────

def _srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    a = 0.055
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + a) / (1 + a)) ** 2.4)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """``(H,W,3)`` uint8/float RGB in 0-255 -> CIELAB float (L 0-100)."""
    rgb = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = _srgb_to_linear(rgb)
    m = np.array(
        [[0.4124564, 0.3575761, 0.1804375],
         [0.2126729, 0.7151522, 0.0721750],
         [0.0193339, 0.1191920, 0.9503041]]
    )
    xyz = lin @ m.T
    # Normalize by D65 white point.
    xyz /= np.array([0.95047, 1.0, 1.08883])
    eps = 216 / 24389
    kappa = 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    lab = np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)
    return lab


# ── Image helpers ─────────────────────────────────────────────────────────────

def _load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def _to_array(im: Image.Image) -> np.ndarray:
    return np.asarray(im, dtype=np.float32)


def _local_std(luma: np.ndarray, sigma: float = 2.0) -> np.ndarray:
    """Local standard deviation of luma (a texture/detail map)."""
    mean = ndimage.gaussian_filter(luma, sigma)
    mean_sq = ndimage.gaussian_filter(luma * luma, sigma)
    return np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))


# ── Step 2: global tone harmonization ────────────────────────────────────────

def harmonize_tone(
    base: np.ndarray, model: np.ndarray, stable: np.ndarray
) -> np.ndarray:
    """Linearly map ``model`` per channel to match ``base`` on ``stable`` px.

    ``stable`` is a boolean mask of pixels believed unchanged (the background
    + skin that the model only re-graded, not edited). Fitting the gain/bias on
    those pixels neutralizes the model's global exposure / white-balance drift
    without touching the genuine local edit's color.
    """
    out = np.empty_like(model)
    sel = stable.ravel()
    for c in range(3):
        x = model[..., c].ravel()[sel]
        y = base[..., c].ravel()[sel]
        if x.size < 64 or float(x.std()) < 1e-3:
            out[..., c] = model[..., c]
            continue
        gain, bias = np.polyfit(x, y, 1)
        # Guard against pathological fits (e.g. near-constant channels).
        if not (0.5 < gain < 2.0):
            gain, bias = 1.0, float(y.mean() - x.mean())
        out[..., c] = np.clip(model[..., c] * gain + bias, 0, 255)
    return out


# ── Step 3: change mask ───────────────────────────────────────────────────────

def build_change_mask(
    base: np.ndarray,
    model: np.ndarray,
    cfg: CompositeConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(alpha, hard_mask)``.

    ``alpha`` is the feathered float blend weight for the model output in
    ``[0,1]``; ``hard_mask`` is the boolean pre-feather edit region (used for
    grain matching and diagnostics).

    Change detection uses TWO complementary cues, OR'd together:

    * **colour** - CIELAB ΔE between base and (harmonized) model;
    * **texture** - the change in local luma standard deviation.

    The colour cue alone under-segments a garment whose colour resembles what
    it replaced (e.g. a smooth light garment over a light top): ΔE falls below
    threshold and the mask develops holes, so the original bleeds through.
    Validation (eval/compositing_eval.py controlled test) showed region recall
    dropping to ~0.6 in that case. The texture cue catches it: a smooth garment
    over a textured fabric (or vice-versa) differs sharply in local texture
    even when the mean colour matches, with a ~10x garment/background
    separation - while staying clear of the (flat) background.
    """
    delta = np.linalg.norm(rgb_to_lab(base) - rgb_to_lab(model), axis=-1)
    delta = ndimage.gaussian_filter(delta, sigma=cfg.blur_sigma)

    base_luma = base @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    model_luma = model @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    texture = np.abs(_local_std(base_luma) - _local_std(model_luma))
    texture = ndimage.gaussian_filter(texture, sigma=cfg.blur_sigma)

    hard = (delta > cfg.delta_e_threshold) | (texture > cfg.texture_threshold)

    # Drop small specks (JPEG ringing, faint global residue).
    if hard.any():
        labels, n = ndimage.label(hard)
        if n:
            areas = ndimage.sum(np.ones_like(labels), labels, index=range(1, n + 1))
            min_area = cfg.min_region_frac * hard.size
            keep = {i + 1 for i, a in enumerate(areas) if a >= min_area}
            hard = np.isin(labels, list(keep)) if keep else np.zeros_like(hard)

    # Solidify the edit: close gaps, fill interior holes, grow for shadows.
    hard = ndimage.binary_closing(hard, iterations=2)
    hard = ndimage.binary_fill_holes(hard)
    if cfg.dilate_px > 0:
        hard = ndimage.binary_dilation(hard, iterations=cfg.dilate_px)

    alpha = ndimage.gaussian_filter(hard.astype(np.float32), sigma=cfg.feather_px)
    # Re-anchor the core to 1.0 so the jewelry centre is 100% model output.
    core = ndimage.binary_erosion(hard, iterations=max(1, int(cfg.feather_px)))
    alpha[core] = 1.0
    alpha = np.clip(alpha, 0.0, 1.0)
    return alpha, hard


# ── Step 5: grain match ──────────────────────────────────────────────────────

def _luma_noise_sigma(arr: np.ndarray, region: np.ndarray) -> float:
    """Estimate sensor-noise stddev (high-freq luma) over ``region`` px."""
    luma = arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    hf = luma - ndimage.gaussian_filter(luma, sigma=1.0)
    if region.any():
        return float(hf[region].std())
    return float(hf.std())


def match_grain(
    composite: np.ndarray,
    base: np.ndarray,
    hard: np.ndarray,
    alpha: np.ndarray,
    cfg: CompositeConfig,
) -> np.ndarray:
    """Add grain to the edit region so it matches the surrounding photo.

    The model denoises whatever it renders, so the jewelry comes back cleaner
    than the noisy original. We measure the input's grain in a ring *around*
    the edit and re-inject matching monochrome noise inside it.
    """
    if cfg.grain_strength <= 0 or not hard.any():
        return composite
    ring = ndimage.binary_dilation(hard, iterations=12) & ~hard
    target = _luma_noise_sigma(base, ring if ring.any() else ~hard)
    have = _luma_noise_sigma(composite, hard)
    deficit = max(0.0, target - have)
    if deficit < 0.5:  # already grainy enough; don't crunch it
        return composite
    rng = np.random.default_rng(0)  # deterministic: stable eval & tests
    noise = rng.normal(0.0, deficit * cfg.grain_strength, size=alpha.shape)
    out = composite + (noise * alpha)[..., None]
    return np.clip(out, 0, 255)


# ── Orchestration ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompositeResult:
    image: Image.Image
    edit_fraction: float       # fraction of pixels taken from the model
    applied: bool              # False => returned raw output (safety bail)
    reason: str = ""


def composite_arrays(
    base: np.ndarray,
    model: np.ndarray,
    *,
    cfg: CompositeConfig = DEFAULT_CONFIG,
) -> tuple[np.ndarray, dict]:
    """Core array-level composite. Returns ``(result_uint8, info)``."""
    base = base.astype(np.float32)
    model = model.astype(np.float32)

    # A rough first-pass diff identifies "stable" pixels for tone fitting.
    rough = np.linalg.norm(rgb_to_lab(base) - rgb_to_lab(model), axis=-1)
    stable = rough < np.quantile(rough, 0.80)

    harmonized = harmonize_tone(base, model, stable) if cfg.tone_harmonize else model

    alpha, hard = build_change_mask(base, harmonized, cfg)
    edit_frac = float(hard.mean())

    info = {"edit_fraction": edit_frac, "applied": True, "reason": ""}
    if edit_frac <= 0:
        info.update(applied=False, reason="empty change mask")
        return np.clip(model, 0, 255).astype(np.uint8), info
    if edit_frac > cfg.max_edit_frac:
        info.update(applied=False, reason=f"edit region too large ({edit_frac:.0%})")
        return np.clip(model, 0, 255).astype(np.uint8), info

    a = alpha[..., None]
    out = base * (1.0 - a) + harmonized * a
    out = match_grain(out, base, hard, alpha, cfg)
    return np.clip(out, 0, 255).astype(np.uint8), info


def composite_bytes(
    base_photo: Path,
    model_image_bytes: bytes,
    *,
    cfg: CompositeConfig = DEFAULT_CONFIG,
) -> CompositeResult:
    """Composite ``model_image_bytes`` onto the original ``base_photo``.

    Output keeps the base photo's resolution and is returned as a PIL image.
    Never raises on a degenerate edit: it falls back to the raw model output.
    """
    base_im = _load_rgb(base_photo)
    with Image.open(io.BytesIO(model_image_bytes)) as m:
        model_im = ImageOps.exif_transpose(m).convert("RGB")

    out_size = base_im.size  # (w, h) of the original photo

    # Compositing assumes the model output shares the base photo's framing
    # (guaranteed in production by imageConfig aspect pinning). If the aspect
    # ratios disagree the model re-cropped the scene, so the pixel grids are
    # NOT comparable - fall back to the raw output rather than warp it.
    base_ratio = base_im.width / base_im.height
    model_ratio = model_im.width / model_im.height
    if abs(math.log(model_ratio / base_ratio)) > 0.06:
        logger.info(
            "compositing skip reason=aspect_mismatch base=%.3f model=%.3f",
            base_ratio, model_ratio,
        )
        return CompositeResult(
            image=model_im,  # keep native framing; do not warp
            edit_fraction=1.0, applied=False, reason="aspect mismatch",
        )
    # Process at a bounded resolution for speed, then upscale alpha-free result.
    long_edge = max(out_size)
    scale = min(1.0, cfg.work_size / long_edge)
    proc_size = (max(1, round(out_size[0] * scale)), max(1, round(out_size[1] * scale)))

    base_proc = base_im.resize(proc_size, Image.LANCZOS)
    model_proc = model_im.resize(proc_size, Image.LANCZOS)

    result_arr, info = composite_arrays(
        _to_array(base_proc), _to_array(model_proc), cfg=cfg
    )
    result_im = Image.fromarray(result_arr).resize(out_size, Image.LANCZOS)

    if not info["applied"]:
        logger.info("compositing bail reason=%s edit_frac=%.3f",
                    info["reason"], info["edit_fraction"])
        # Return the raw model output at the base resolution for consistency.
        result_im = model_im.resize(out_size, Image.LANCZOS)

    logger.info(
        "compositing done applied=%s edit_frac=%.3f",
        info["applied"], info["edit_fraction"],
    )
    return CompositeResult(
        image=result_im,
        edit_fraction=info["edit_fraction"],
        applied=info["applied"],
        reason=info["reason"],
    )


def composite_to_bytes(result: CompositeResult, mime: str) -> tuple[bytes, str]:
    """Encode a composite result back to bytes, preserving PNG vs JPEG."""
    buf = io.BytesIO()
    if "png" in mime:
        result.image.save(buf, "PNG")
        return buf.getvalue(), "image/png"
    result.image.save(buf, "JPEG", quality=95)
    return buf.getvalue(), "image/jpeg"
