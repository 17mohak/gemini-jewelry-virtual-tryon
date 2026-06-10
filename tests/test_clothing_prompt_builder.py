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
    assert "lower-body clothing exactly as it is" in top
    assert "skirt" in dress
    assert "lower-body garment" in trousers
    assert "upper-body clothing exactly as it is" in trousers


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
