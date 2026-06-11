"""Type-aware prompt construction for clothing virtual try-on (Part 2, bonus).

Kept deliberately separate from the jewelry prompt builder: clothing
replacement is a *garment swap* (remove one garment, fit another to the body),
while jewelry is a pure *addition* — the preservation rules, placement physics
and failure modes differ enough that sharing prompt text would muddy both.

All clothing types use the same user photo kind: a full-body photo.

Evaluation-driven design notes:

* The original prompt allowed clothing to "naturally cover" accessories and
  footwear - the model used that loophole to lengthen garments and erase the
  wearer's legs (observed midi -> floor-length drift). v2 removes the loophole
  and adds explicit hem landmarks plus a visible-skin conservation rule.
* Each catalog item carries a structured ``coverage`` field stating exactly
  which body regions the garment covers and which must remain visible; the
  builder injects it as a hard geometry constraint.
* A photographic-character section requires the new fabric to inherit the
  photo's flash/noise/sharpness - evaluation showed garments rendered with
  clean studio shading pasted into noisy flash photos.
"""

from __future__ import annotations

from typing import Mapping

CLOTHING_TYPES = frozenset({"top", "dress", "trousers"})

PHOTO_KIND_BODY = "body"


def required_photo_kind(clothing_type: str) -> str:
    """All supported clothing types are tried on against a full-body photo."""
    t = (clothing_type or "").strip().lower()
    if t in CLOTHING_TYPES:
        return PHOTO_KIND_BODY
    raise ValueError(
        f"Unsupported clothing type: {clothing_type!r}. "
        f"Supported types: {', '.join(sorted(CLOTHING_TYPES))}"
    )


# ── Per-type fit instructions ─────────────────────────────────────────────────
# Written like directions to a fitting tailor: which garment is replaced, how
# the new one sits on the body, and how fabric behaves.

_FIT: Mapping[str, str] = {
    "top": (
        "Replace ONLY the person's upper-body garment with the product top. "
        "Fit it naturally to their torso and shoulders: sleeves follow the "
        "arms' pose, the neckline sits where the product's neckline is "
        "designed to sit, and the hem ends exactly where it ends in the "
        "product photo (relative to the waist and hips) - never lower. "
        "Render realistic fabric behavior - soft folds at the elbows and "
        "waist, gentle tension across the shoulders - consistent with the "
        "person's pose. The lower body (trousers, skirt, legs, shoes) stays "
        "exactly as in Image 1."
    ),
    "dress": (
        "Replace the person's current outfit with the product dress. Fit the "
        "bodice naturally to their torso, with the waistline at their natural "
        "waist. The skirt drapes with gravity and its hem ends at EXACTLY the "
        "same point on the body as in the product photo - measure it against "
        "body landmarks (knee, mid-calf, ankle) and do not render the dress "
        "longer or shorter than the product. Everything below that hem "
        "(lower legs, ankles, footwear, hosiery) remains exactly as visible "
        "as it is in Image 1. Sleeves or straps follow the product's design "
        "and the person's pose. Render realistic fabric folds and drape "
        "consistent with how they are standing."
    ),
    "trousers": (
        "Replace ONLY the person's lower-body garment with the product "
        "trousers. Fit them naturally at the waist and hips, with the legs "
        "following the person's stance and natural creases at the knees. The "
        "hem ends exactly where it ends in the product photo (at the ankle "
        "unless the product shows otherwise) - shoes and feet remain exactly "
        "as in Image 1. The upper-body clothing stays exactly as in Image 1."
    ),
}

_PRESERVATION = (
    "Image 1 is the base photograph and must remain the same photo of the "
    "same person. Preserve EXACTLY: the person's facial identity and facial "
    "features, expression, skin tone and skin texture, hairstyle and hair "
    "color, body shape and proportions, pose, all visible accessories, all "
    "footwear, the background, and the framing/crop. Visible-skin rule: "
    "every area of the person's skin that is visible in Image 1 and that the "
    "product garment does not genuinely cover (by its real cut shown in "
    "Image 2) must remain visible and unchanged - do not extend fabric over "
    "arms, legs, neckline or feet that the product would leave exposed. The "
    "ONLY change allowed is the garment swap described above."
)

_PHOTOGRAPHIC_CHARACTER = (
    "Image 1 has a specific photographic character: a lighting type (direct "
    "flash, window light, overcast daylight...), a white balance, a sensor "
    "noise / grain level, a sharpness profile and a dynamic range. The "
    "finished image must keep that character EVERYWHERE, and the new garment "
    "must be rendered WITH it: on a noisy night flash photo the fabric shows "
    "hard flash falloff, real speculars where the material is shiny, and the "
    "same grain as the surrounding skin and scene; in soft daylight it shows "
    "soft shading. The fabric must not look cleaner, smoother or more evenly "
    "lit than the rest of the photograph. Do not denoise, sharpen, brighten, "
    "re-grade or beautify any part of the image."
)

_FIDELITY_RULES = (
    "Reproduce the garment from Image 2 with complete fidelity: identical "
    "color, identical pattern (scale, direction and alignment), identical "
    "fabric appearance and sheen, identical cut, length and design details "
    "(collars, buttons, pockets, seams, ties). Re-light the garment so its "
    "shading comes from the SAME light sources as the base photo, and let "
    "the pattern follow the body's contours realistically - but do NOT "
    "redesign, recolor, lengthen, shorten or restyle the garment in any way."
)

_HARD_CONSTRAINTS = (
    "Hard rules - the result is rejected if any of these are violated:\n"
    "- The output must be photorealistic, indistinguishable from a real "
    "photograph of this person wearing this garment.\n"
    "- No 'pasted-on' effect: the garment must wrap the body with correct "
    "perspective, fit, folds, occlusion and contact shadows.\n"
    "- No distortion of the person: face, hair, hands, legs and body "
    "proportions must not change.\n"
    "- Do not change the garment's color, pattern, cut, length or design.\n"
    "- Do not cover body regions the product's real cut leaves exposed; do "
    "not erase or invent legs, arms, hands or feet.\n"
    "- Do not change, replace or noticeably drift the background.\n"
    "- No style-transfer artifacts and no AI-fashion glamour: no "
    "painting/cartoon/CGI look, no added filters, no skin smoothing, no "
    "editorial relighting, no change to grain, sharpness or white balance.\n"
    "- Do not add any clothing, accessories, text, logos or watermarks "
    "other than the single product described.\n"
    "- Output exactly one edited image with the SAME framing, crop and "
    "aspect ratio as Image 1 - do not zoom in, zoom out, rotate or extend "
    "the scene."
)


def build_clothing_tryon_prompt(item: Mapping[str, str]) -> str:
    """Build the full clothing try-on edit prompt for a catalog item.

    ``item`` is a catalog entry with at least ``name``, ``type`` and
    ``description``. Optional fields: ``prompt_hint`` (item-specific
    instruction) and ``coverage`` (structured statement of which body regions
    the garment covers and which must stay visible - injected as a hard
    geometry constraint).
    """
    clothing_type = (item.get("type") or "").strip().lower()
    required_photo_kind(clothing_type)  # validates the type

    name = (item.get("name") or clothing_type).strip()
    description = (item.get("description") or "").strip()
    hint = (item.get("prompt_hint") or "").strip()
    coverage = (item.get("coverage") or "").strip()

    product_block = f'The product is "{name}" ({clothing_type}): {description}'
    if hint:
        product_block += f"\nItem-specific instruction: {hint}"

    fit_block = "Fit: " + _FIT[clothing_type]
    if coverage:
        fit_block += (
            f"\nCoverage constraint for this exact garment: {coverage} "
            "Body regions outside this coverage stay exactly as in Image 1."
        )

    sections = [
        (
            "You are a professional fashion photo retoucher performing a "
            "virtual clothing try-on edit. You are given two images. Image 1 "
            "is a full-body photograph of a person. Image 2 is a studio "
            "product photograph of a garment. Edit Image 1 so the person is "
            "naturally WEARING the garment from Image 2."
        ),
        product_block,
        fit_block,
        "Preservation: " + _PRESERVATION,
        "Photographic character: " + _PHOTOGRAPHIC_CHARACTER,
        "Garment fidelity: " + _FIDELITY_RULES,
        _HARD_CONSTRAINTS,
    ]
    return "\n\n".join(sections)


def build_video_prompt(item: Mapping[str, str]) -> str:
    """Motion prompt for the clothing try-on video (LTX 2.3)."""
    name = (item.get("name") or "outfit").strip()
    return (
        f"A short elegant fashion shot of a person wearing the {name}. The "
        "person subtly shifts their weight and turns slightly, so the fabric "
        "moves naturally with them. Camera is static. Lighting, identity, "
        "hairstyle and background remain exactly as in the source image. "
        "Photorealistic, smooth, subtle motion only - no morphing, no "
        "warping, no scene change."
    )
