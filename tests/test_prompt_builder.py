"""Tests for the type-aware Gemini prompt builder."""

import pytest

from backend.services import prompt_builder as pb


# ── Jewelry type -> photo kind mapping ───────────────────────────────────────

@pytest.mark.parametrize("jewelry_type", ["necklace", "earrings"])
def test_face_types_map_to_face_photo(jewelry_type):
    assert pb.required_photo_kind(jewelry_type) == pb.PHOTO_KIND_FACE


@pytest.mark.parametrize("jewelry_type", ["ring", "bracelet"])
def test_hand_types_map_to_hand_photo(jewelry_type):
    assert pb.required_photo_kind(jewelry_type) == pb.PHOTO_KIND_HAND


def test_mapping_is_case_and_whitespace_insensitive():
    assert pb.required_photo_kind("  Necklace ") == pb.PHOTO_KIND_FACE
    assert pb.required_photo_kind("RING") == pb.PHOTO_KIND_HAND


@pytest.mark.parametrize("bad", ["tiara", "watch", "", None])
def test_unknown_type_raises(bad):
    with pytest.raises(ValueError):
        pb.required_photo_kind(bad)


# ── Try-on prompt content ────────────────────────────────────────────────────

NECKLACE = {
    "id": "n1",
    "name": "Gold Cross Pendant Necklace",
    "type": "necklace",
    "description": "Byzantine-style gold chain with an embossed cross pendant.",
}
RING = {
    "id": "r1",
    "name": "Three-Stone Diamond Ring",
    "type": "ring",
    "description": "White-gold ring with three brilliant-cut diamonds.",
    "prompt_hint": "Apply ONLY the three-stone diamond ring.",
}


def test_prompt_includes_item_name_and_description():
    prompt = pb.build_tryon_prompt(NECKLACE)
    assert NECKLACE["name"] in prompt
    assert NECKLACE["description"] in prompt


def test_prompt_includes_optional_hint_when_present():
    assert RING["prompt_hint"] in pb.build_tryon_prompt(RING)
    assert "Item-specific instruction" not in pb.build_tryon_prompt(NECKLACE)


def test_prompt_adapts_placement_to_type():
    necklace_prompt = pb.build_tryon_prompt(NECKLACE).lower()
    ring_prompt = pb.build_tryon_prompt(RING).lower()
    assert "collarbone" in necklace_prompt
    assert "finger" in ring_prompt
    assert necklace_prompt != ring_prompt


def test_prompt_references_correct_user_photo_kind():
    assert "person's face" in pb.build_tryon_prompt(NECKLACE)
    assert "person's hand" in pb.build_tryon_prompt(RING)


@pytest.mark.parametrize("item", [NECKLACE, RING])
def test_prompt_contains_mandatory_constraints(item):
    """The assignment's explicit prompt requirements must all be present."""
    prompt = pb.build_tryon_prompt(item).lower()
    assert "photorealistic" in prompt
    assert "pasted" in prompt           # no pasted-on effect
    assert "distortion" in prompt       # no distortion
    assert "skin tone" in prompt        # preserve skin tone
    assert "lighting" in prompt         # preserve lighting
    assert "background" in prompt       # no background drift
    assert "style" in prompt            # no style-transfer artifacts
    assert "shape, material, color" in prompt  # jewelry fidelity


def test_prompt_preserves_identity_for_face_items():
    prompt = pb.build_tryon_prompt(NECKLACE).lower()
    assert "facial identity" in prompt
    assert "hairstyle" in prompt


def test_prompt_preserves_hand_structure_for_hand_items():
    prompt = pb.build_tryon_prompt(RING).lower()
    assert "hand's structure" in prompt


def test_prompt_rejects_unknown_type():
    with pytest.raises(ValueError):
        pb.build_tryon_prompt({"name": "Crown", "type": "crown", "description": "x"})


# ── Video prompt ─────────────────────────────────────────────────────────────

def test_video_prompt_adapts_to_photo_kind():
    face_video = pb.build_video_prompt(NECKLACE).lower()
    hand_video = pb.build_video_prompt(RING).lower()
    assert "head" in face_video
    assert "hand" in hand_video
    assert "photorealistic" in face_video
