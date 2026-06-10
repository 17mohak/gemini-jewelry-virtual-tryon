"""Type-aware prompt construction for jewelry virtual try-on.

This module is the core of the assignment: it assembles a strict, structured
edit instruction for the image model (Nano Banana) from (a) the jewelry type
and (b) the selected catalog item. Nothing here is a single static string —
every section adapts to the item being tried on.

Design notes (also summarized in the README):

* Image-editing models respond best to prompts that (1) name each input image
  explicitly, (2) describe the desired *physical* placement of the jewelry the
  way a photographer would, and (3) spell out negative constraints as hard
  rules rather than vague wishes ("do not change facial identity" beats
  "keep the person similar").
* The jewelry description from the catalog is injected verbatim so the model
  anchors on the actual product (shape / material / color) instead of
  hallucinating a generic item of that category.
* Per-type placement physics (drape, gravity, occlusion, contact shadows)
  is what prevents the "pasted-on sticker" look the assignment warns about.
"""

from __future__ import annotations

from typing import Mapping

# ── Jewelry type -> which user photo is required ─────────────────────────────

FACE_TYPES = frozenset({"necklace", "earrings"})
HAND_TYPES = frozenset({"ring", "bracelet"})
SUPPORTED_TYPES = FACE_TYPES | HAND_TYPES

PHOTO_KIND_FACE = "face"
PHOTO_KIND_HAND = "hand"


def required_photo_kind(jewelry_type: str) -> str:
    """Map a jewelry type to the user photo it must be rendered on.

    necklace / earrings -> "face" (head & shoulders photo)
    ring / bracelet     -> "hand" (hand / wrist photo)
    """
    t = (jewelry_type or "").strip().lower()
    if t in FACE_TYPES:
        return PHOTO_KIND_FACE
    if t in HAND_TYPES:
        return PHOTO_KIND_HAND
    raise ValueError(
        f"Unsupported jewelry type: {jewelry_type!r}. "
        f"Supported types: {', '.join(sorted(SUPPORTED_TYPES))}"
    )


# ── Per-type placement instructions ──────────────────────────────────────────
# Written like directions to a retoucher: where the piece sits, how it hangs,
# what it touches, and what may occlude it.

_PLACEMENT: Mapping[str, str] = {
    "necklace": (
        "Place the necklace around the person's neck so that it drapes "
        "naturally with gravity: the chain follows the curve of the neck and "
        "rests on the skin at the collarbones, and any pendant hangs centered "
        "at the lowest point of the chain. Match the necklace's perspective to "
        "the person's pose and camera angle. If hair, clothing or chin "
        "naturally overlaps parts of the necklace, let them occlude it "
        "realistically. Add the soft contact shadows the necklace would cast "
        "on the skin and clothing under the photo's existing lighting."
    ),
    "earrings": (
        "Place the earrings on BOTH ears as a matching pair, attached at the "
        "earlobes and hanging straight down with gravity regardless of head "
        "tilt. Match their perspective to the head pose: if one ear is partly "
        "turned away or covered by hair, show that earring partially occluded "
        "or foreshortened, exactly as a real photo would. Keep both earrings "
        "identical in design and scale them realistically relative to the "
        "ears. Add the subtle skin contact points and tiny shadows where the "
        "earrings touch the lobes."
    ),
    "ring": (
        "Place the ring on the ring finger of the visible hand, with the band "
        "wrapping fully around the finger between the knuckle and the base "
        "joint. The band must follow the finger's cylindrical shape and "
        "perspective, partially hidden where the finger curves away from the "
        "camera. The face of the ring sits on top of the finger, oriented "
        "with the hand's pose. Scale it to a realistic ring size for this "
        "hand, and add the slight contact shadow the band casts on the skin."
    ),
    "bracelet": (
        "Place the bracelet around the wrist of the visible hand so it wraps "
        "the wrist completely, hanging with natural looseness and resting "
        "against the wrist bone with gravity. Parts of the bracelet must be "
        "hidden where the wrist curves away from the camera. Match the "
        "bracelet's perspective and ellipse to the wrist's angle, scale it to "
        "a realistic bracelet size, and add the soft contact shadow it casts "
        "on the skin and on any clothing it touches."
    ),
}

# ── Identity-preservation block, per photo kind ──────────────────────────────

_PRESERVATION: Mapping[str, str] = {
    PHOTO_KIND_FACE: (
        "Image 1 is the base photograph and must remain the same photo of the "
        "same person. Preserve EXACTLY: the person's facial identity and "
        "facial features, facial expression, skin tone and skin texture, "
        "hairstyle and hair color, clothing, body pose, the background, the "
        "framing/crop, and the original lighting direction, color temperature "
        "and overall image style (grain, sharpness, white balance). The ONLY "
        "change allowed is the addition of the jewelry described below."
    ),
    PHOTO_KIND_HAND: (
        "Image 1 is the base photograph and must remain the same photo of the "
        "same hand. Preserve EXACTLY: the hand's structure, finger positions "
        "and proportions, skin tone and skin texture, nails, any existing "
        "clothing or sleeves, the background, the framing/crop, and the "
        "original lighting direction, color temperature and overall image "
        "style (grain, sharpness, white balance). The ONLY change allowed is "
        "the addition of the jewelry described below."
    ),
}

# ── Constraint blocks shared by all types ────────────────────────────────────

_FIDELITY_RULES = (
    "Reproduce the jewelry from Image 2 with complete fidelity: identical "
    "shape and silhouette, identical materials and surface finish, identical "
    "colors, identical gemstones (count, cut, color and arrangement), and "
    "identical proportions. Re-light the jewelry so its highlights and "
    "reflections come from the SAME light sources as the base photo, but do "
    "NOT redesign, simplify, recolor or restyle it in any way."
)

_HARD_CONSTRAINTS = (
    "Hard rules - the result is rejected if any of these are violated:\n"
    "- The output must be photorealistic, indistinguishable from a real "
    "photograph taken of this person wearing this jewelry.\n"
    "- No 'pasted-on' or sticker effect: the jewelry must sit ON the body "
    "with correct perspective, scale, occlusion, contact shadows and "
    "scene-matched reflections.\n"
    "- No distortion or warping of the person or the jewelry.\n"
    "- Do not change the jewelry's shape, material, color or design.\n"
    "- Do not change the person's identity, face, skin tone or body.\n"
    "- Do not change, replace or noticeably drift the background.\n"
    "- No style-transfer artifacts: no painting/cartoon/CGI look, no added "
    "filters, no beautification or skin smoothing.\n"
    "- Do not add any jewelry, accessories, text, logos or watermarks other "
    "than the single product described.\n"
    "- Output exactly one edited image at the same framing as Image 1."
)


def build_tryon_prompt(item: Mapping[str, str]) -> str:
    """Build the full image-edit prompt for a catalog item.

    ``item`` is a catalog entry with at least ``name``, ``type`` and
    ``description``; an optional ``prompt_hint`` adds item-specific guidance
    (e.g. "the product photo shows two rings - apply only one").
    """
    jewelry_type = (item.get("type") or "").strip().lower()
    photo_kind = required_photo_kind(jewelry_type)  # validates the type

    name = (item.get("name") or jewelry_type).strip()
    description = (item.get("description") or "").strip()
    hint = (item.get("prompt_hint") or "").strip()

    product_block = f'The product is "{name}" ({jewelry_type}): {description}'
    if hint:
        product_block += f"\nItem-specific instruction: {hint}"

    sections = [
        (
            "You are a professional photo retoucher performing a virtual "
            "jewelry try-on edit. You are given two images. Image 1 is a "
            f"photograph of a person's {photo_kind}. Image 2 is a studio "
            "product photograph of a piece of jewelry. Edit Image 1 so the "
            "person is naturally WEARING the jewelry from Image 2."
        ),
        product_block,
        "Placement: " + _PLACEMENT[jewelry_type],
        "Preservation: " + _PRESERVATION[photo_kind],
        "Jewelry fidelity: " + _FIDELITY_RULES,
        _HARD_CONSTRAINTS,
    ]
    return "\n\n".join(sections)


def build_video_prompt(item: Mapping[str, str]) -> str:
    """Build the short motion prompt for the image-to-video step (LTX 2.3).

    The try-on image is the video's first frame, so this prompt only describes
    gentle motion; all preservation work already happened in the image step.
    """
    jewelry_type = (item.get("type") or "").strip().lower()
    photo_kind = required_photo_kind(jewelry_type)
    name = (item.get("name") or jewelry_type).strip()

    if photo_kind == PHOTO_KIND_FACE:
        motion = (
            "The person slowly and subtly turns their head a few degrees and "
            "smiles softly, so the light catches the jewelry."
        )
    else:
        motion = (
            "The hand slowly and gracefully rotates a few degrees, showing "
            "the jewelry from slightly different angles as light glints off it."
        )

    return (
        f"A short elegant close-up beauty shot of a person wearing the {name}. "
        f"{motion} Camera is static. Lighting, identity, skin tone, clothing "
        "and background remain exactly as in the source image. Photorealistic, "
        "smooth, subtle motion only - no morphing, no warping, no scene change."
    )
