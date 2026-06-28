"""Tests for the clothing (Part 2) prompt builder."""

import pytest

from backend.services import clothing_prompt_builder as cpb


# ── Clothing type -> photo kind mapping ──────────────────────────────────────

@pytest.mark.parametrize("clothing_type", ["top", "dress", "trousers"])
def test_all_clothing_types_use_body_photo(clothing_type):
    assert cpb.required_photo_kind(clothing_type) == cpb.PHOTO_KIND_BODY


@pytest.mark.parametrize("bad", ["necklace", "shoes", "", None])
def test_unknown_clothing_type_raises(bad):
    with pytest.raises(ValueError):
        cpb.required_photo_kind(bad)


# ── Prompt content ───────────────────────────────────────────────────────────

TOP = {
    "id": "c1",
    "name": "Breton Striped Top",
    "type": "top",
    "description": "Navy and white striped long-sleeve cotton top.",
    "prompt_hint": "Stripes must stay evenly spaced.",
}
DRESS = {
    "id": "c2",
    "name": "Emerald Wrap Midi Dress",
    "type": "dress",
    "description": "Emerald-green wrap dress with a tie waist.",
}
TROUSERS = {
    "id": "c3",
    "name": "Light-Blue Straight Jeans",
    "type": "trousers",
    "description": "Light-blue straight-leg jeans.",
}


def test_prompt_includes_item_name_description_and_hint():
    prompt = cpb.build_clothing_tryon_prompt(TOP)
    assert TOP["name"] in prompt
    assert TOP["description"] in prompt
    assert TOP["prompt_hint"] in prompt


def test_prompt_adapts_fit_section_to_type():
    top = cpb.build_clothing_tryon_prompt(TOP).lower()
    dress = cpb.build_clothing_tryon_prompt(DRESS).lower()
    trousers = cpb.build_clothing_tryon_prompt(TROUSERS).lower()
    assert "upper-body garment" in top
    assert "lower body (trousers, skirt, legs, shoes) stays exactly as in image 1" in top
    assert "skirt" in dress
    assert "lower-body garment" in trousers
    assert "upper-body clothing stays exactly as in image 1" in trousers


@pytest.mark.parametrize("item", [TOP, DRESS, TROUSERS])
def test_prompt_contains_mandatory_constraints(item):
    prompt = cpb.build_clothing_tryon_prompt(item).lower()
    assert "photorealistic" in prompt
    assert "pasted" in prompt
    assert "body shape and proportions" in prompt   # no anatomy drift
    assert "facial identity" in prompt              # identity preserved
    assert "pattern" in prompt                      # garment fidelity
    assert "background" in prompt
    assert "style-transfer" in prompt
    assert "full-body photograph" in prompt         # correct photo routing


def test_prompt_rejects_unknown_type():
    with pytest.raises(ValueError):
        cpb.build_clothing_tryon_prompt({"name": "Boots", "type": "shoes", "description": "x"})


def test_video_prompt_mentions_fabric_motion():
    video = cpb.build_video_prompt(DRESS).lower()
    assert "fabric" in video
    assert "photorealistic" in video


# ── v2 quality rules (driven by the image-quality audit) ─────────────────────

def test_no_coverage_loophole_remains():
    """The phrase that let the model extend garments over legs is gone."""
    for item in (TOP, DRESS, TROUSERS):
        prompt = cpb.build_clothing_tryon_prompt(item).lower()
        assert "unless the garment naturally covers" not in prompt


def test_visible_skin_conservation_rule_present():
    prompt = cpb.build_clothing_tryon_prompt(DRESS).lower()
    assert "visible-skin rule" in prompt
    assert "do not extend fabric over" in prompt


def test_dress_prompt_has_hem_landmark_constraints():
    prompt = cpb.build_clothing_tryon_prompt(DRESS).lower()
    assert "hem ends at exactly the same point on the body" in prompt
    assert "knee, mid-calf, ankle" in prompt
    assert "do not render the dress longer or shorter" in prompt


def test_coverage_field_is_injected_as_constraint():
    dress_with_coverage = dict(
        DRESS, coverage="Covers the torso; hem at the knee; lower legs stay visible."
    )
    prompt = cpb.build_clothing_tryon_prompt(dress_with_coverage)
    assert "Coverage constraint for this exact garment" in prompt
    assert "hem at the knee" in prompt
    # without the field, no empty constraint block appears
    assert "Coverage constraint" not in cpb.build_clothing_tryon_prompt(DRESS)


def test_clothing_prompt_has_photographic_character_rules():
    prompt = cpb.build_clothing_tryon_prompt(TOP).lower()
    assert "photographic character" in prompt
    assert "noise" in prompt
    assert "white balance" in prompt
    assert "must not look cleaner, smoother or more evenly lit" in prompt


# ── v3 quality rules (adversarial garment stress audit) ──────────────────────

@pytest.mark.parametrize("clothing_type", ["skirt", "jacket", "set"])
def test_expanded_taxonomy_uses_body_photo(clothing_type):
    assert cpb.required_photo_kind(clothing_type) == cpb.PHOTO_KIND_BODY


def test_skirt_keeps_legs_bare_and_is_not_trousers():
    prompt = cpb.build_clothing_tryon_prompt(
        {"name": "Wrap Mini Skirt", "type": "skirt", "description": "a wrap mini skirt"}
    ).lower()
    assert "lower-body garment with the product skirt" in prompt
    assert "do not render trouser legs" in prompt
    assert "bare and fully visible" in prompt


def test_jacket_layering_preserves_underlayer():
    prompt = cpb.build_clothing_tryon_prompt(
        {"name": "Track Jacket", "type": "jacket", "description": "a denim track jacket",
         "layer": "over"}
    ).lower()
    assert "outerwear worn over" in prompt
    assert "do not delete or replace the layer underneath" in prompt
    # A swap-style jacket (no layer field) must NOT emit the layering block.
    swap = cpb.build_clothing_tryon_prompt(
        {"name": "Blazer", "type": "jacket", "description": "a blazer"}
    ).lower()
    assert "outerwear worn over" not in swap


def test_set_keeps_two_pieces_separate():
    prompt = cpb.build_clothing_tryon_prompt(
        {"name": "Grommet Two-Piece", "type": "set",
         "description": "a one-shoulder crop top and matching mini skirt"}
    ).lower()
    assert "two-piece set" in prompt
    assert "do not join the two pieces into a single dress" in prompt


def test_material_physics_is_keyword_triggered():
    sequin = cpb.build_clothing_tryon_prompt(
        {"name": "Sequin Dress", "type": "dress", "description": "a sequin mini dress"}
    ).lower()
    assert "material rendering" in sequin
    assert "each disc as an individual tiny mirror" in sequin

    sheer = cpb.build_clothing_tryon_prompt(
        {"name": "Mesh Skirt", "type": "skirt", "description": "a sheer mesh skirt"}
    ).lower()
    assert "semi-transparent" in sheer

    # A plain garment matches no material keywords -> no extra physics block,
    # so simple catalog items do not regress.
    plain = cpb.build_clothing_tryon_prompt(
        {"name": "Plain Cotton Tee", "type": "top", "description": "a plain cotton t-shirt"}
    ).lower()
    assert "material rendering" not in plain


def test_materials_and_construction_fields_are_anchored():
    prompt = cpb.build_clothing_tryon_prompt({
        "name": "Orchid Gown", "type": "dress",
        "description": "an ivory column gown",
        "materials": "ivory satin with 3D orchid appliques",
        "construction": "halter neckline, floor-length",
    })
    assert "Materials: ivory satin with 3D orchid appliques." in prompt
    assert "Construction: halter neckline, floor-length." in prompt


def test_all_catalog_clothing_items_carry_coverage():
    """Every real catalog item must ship the structured coverage field."""
    import json
    from backend.config import CATALOG_DIR

    items = json.loads((CATALOG_DIR / "clothing.json").read_text(encoding="utf-8"))["items"]
    for item in items:
        assert item.get("coverage"), f"{item['id']} is missing a coverage field"
        assert "remain exactly as" in item["coverage"]
