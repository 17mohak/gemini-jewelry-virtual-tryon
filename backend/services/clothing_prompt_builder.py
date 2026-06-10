"""Type-aware prompt construction for clothing virtual try-on (Part 2, bonus).

Kept deliberately separate from the jewelry prompt builder: clothing
replacement is a *garment swap* (remove one garment, fit another to the body),
while jewelry is a pure *addition* — the preservation rules, placement physics
and failure modes differ enough that sharing prompt text would muddy both.

All clothing types use the same user photo kind: a full-body photo.
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
        "designed to sit, and the hem falls at its natural length. Render "
        "realistic fabric behavior - soft folds at the elbows and waist, "
        "gentle tension across the shoulders - consistent with the person's "
        "pose. Keep their lower-body clothing exactly as it is."
    ),
    "dress": (
        "Replace the person's current outfit with the product dress. Fit the "
        "bodice naturally to their torso, with the waistline at their natural "
        "waist and the skirt draping with gravity to the dress's designed "
        "length. Sleeves or straps follow the product's design and the "
        "person's pose. Render realistic fabric behavior - folds, drape and "
        "gentle swing consistent with how they are standing."
    ),
    "trousers": (
        "Replace ONLY the person's lower-body garment with the product "
        "trousers. Fit them naturally at the waist and hips, with the legs "
        "following the person's stance and natural creases at the knees. The "
        "hem ends at the ankles as the product is designed. Keep their "
        "upper-body clothing exactly as it is."
    ),
}

_PRESERVATION = (
    "Image 1 is the base photograph and must remain the same photo of the "
    "same person. Preserve EXACTLY: the person's facial identity and facial "
    "features, expression, skin tone and skin texture, hairstyle and hair "
    "color, body shape and proportions, pose, any visible accessories and "
    "footwear (unless the garment naturally covers them), the background, "
    "the framing/crop, and the original lighting direction, color "
    "temperature and overall image style. The ONLY change allowed is the "
    "garment swap described above."
)

_FIDELITY_RULES = (
    "Reproduce the garment from Image 2 with complete fidelity: identical "
    "color, identical pattern (scale, direction and alignment), identical "
    "fabric appearance, identical cut and design details (collars, buttons, "
    "pockets, seams, ties). Re-light the garment so its shading comes from "
    "the SAME light sources as the base photo, and let the pattern follow "
    "the body's contours realistically - but do NOT redesign, recolor or "
    "restyle the garment in any way."
)

_HARD_CONSTRAINTS = (
    "Hard rules - the result is rejected if any of these are violated:\n"
    "- The output must be photorealistic, indistinguishable from a real "
    "photograph of this person wearing this garment.\n"
    "- No 'pasted-on' effect: the garment must wrap the body with correct "
    "perspective, fit, folds, occlusion and contact shadows.\n"
    "- No distortion of the person: face, hair, hands, legs and body "
    "proportions must not change.\n"
    "- Do not change the garment's color, pattern, cut or design.\n"
    "- Do not change, replace or noticeably drift the background.\n"
    "- No style-transfer artifacts: no painting/cartoon/CGI look, no added "
    "filters, no skin smoothing.\n"
    "- Do not add any clothing, accessories, text, logos or watermarks "
    "other than the single product described.\n"
    "- Output exactly one edited image at the same framing as Image 1."
)


def build_clothing_tryon_prompt(item: Mapping[str, str]) -> str:
    """Build the full clothing try-on edit prompt for a catalog item."""
    clothing_type = (item.get("type") or "").strip().lower()
    required_photo_kind(clothing_type)  # validates the type

    name = (item.get("name") or clothing_type).strip()
    description = (item.get("description") or "").strip()
    hint = (item.get("prompt_hint") or "").strip()

    product_block = f'The product is "{name}" ({clothing_type}): {description}'
    if hint:
        product_block += f"\nItem-specific instruction: {hint}"

    sections = [
        (
            "You are a professional fashion photo retoucher performing a "
            "virtual clothing try-on edit. You are given two images. Image 1 "
            "is a full-body photograph of a person. Image 2 is a studio "
            "product photograph of a garment. Edit Image 1 so the person is "
            "naturally WEARING the garment from Image 2."
        ),
        product_block,
        "Fit: " + _FIT[clothing_type],
        "Preservation: " + _PRESERVATION,
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
