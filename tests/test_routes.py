"""Route and response-shape tests (external APIs are mocked)."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import app as app_module
from backend.app import app
from backend.config import CATALOG_DIR

client = TestClient(app)


def make_photo_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (180, 150, 120)).save(buf, "JPEG")
    return buf.getvalue()


# ── Health ───────────────────────────────────────────────────────────────────

def test_health_shape():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert set(data) == {"status", "app_env", "nanobanana_configured", "ltx_configured"}


# ── Catalog ──────────────────────────────────────────────────────────────────

def test_catalog_has_at_least_five_items_with_required_fields():
    resp = client.get("/api/catalog")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 5
    for item in items:
        assert {"id", "name", "type", "description", "image_url", "photo_kind"} <= set(item)
        assert item["type"] in {"necklace", "earrings", "ring", "bracelet"}
        assert item["photo_kind"] in {"face", "hand"}


def test_catalog_covers_all_four_jewelry_types():
    types = {item["type"] for item in client.get("/api/catalog").json()}
    assert types == {"necklace", "earrings", "ring", "bracelet"}


def test_catalog_ids_are_unique():
    ids = [item["id"] for item in client.get("/api/catalog").json()]
    assert len(ids) == len(set(ids))


def test_catalog_images_exist_on_disk_and_are_served():
    for item in client.get("/api/catalog").json():
        rel = item["image_url"].removeprefix("/catalog/")
        assert (CATALOG_DIR / rel).exists(), f"missing image for {item['id']}"
    first = client.get("/api/catalog").json()[0]
    assert client.get(first["image_url"]).status_code == 200


# ── Clothing catalog (Part 2) ────────────────────────────────────────────────

def test_clothing_catalog_has_at_least_five_items_needing_body_photo():
    resp = client.get("/api/catalog/clothing")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 5
    for item in items:
        assert item["type"] in {"top", "dress", "trousers"}
        assert item["photo_kind"] == "body"
        rel = item["image_url"].removeprefix("/catalog/")
        assert (CATALOG_DIR / rel).exists(), f"missing image for {item['id']}"


def test_catalog_ids_are_unique_across_both_catalogs():
    jewelry = [i["id"] for i in client.get("/api/catalog").json()]
    clothing = [i["id"] for i in client.get("/api/catalog/clothing").json()]
    combined = jewelry + clothing
    assert len(combined) == len(set(combined))


# ── Try-on validation ────────────────────────────────────────────────────────

def test_tryon_unknown_item_returns_404():
    resp = client.post("/api/tryon", data={"item_id": "no-such-item"})
    assert resp.status_code == 404
    assert "Unknown catalog item" in resp.json()["detail"]


def test_tryon_missing_required_photo_returns_400():
    necklace = next(i for i in client.get("/api/catalog").json() if i["type"] == "necklace")
    # a necklace needs a FACE photo; sending only a hand photo must fail clearly
    resp = client.post(
        "/api/tryon",
        data={"item_id": necklace["id"]},
        files={"hand_photo": ("hand.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 400
    assert "face photo" in resp.json()["detail"]


def test_tryon_rejects_non_image_upload():
    necklace = next(i for i in client.get("/api/catalog").json() if i["type"] == "necklace")
    resp = client.post(
        "/api/tryon",
        data={"item_id": necklace["id"]},
        files={"face_photo": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


# ── Try-on success (Nano Banana + LTX mocked) ────────────────────────────────

@pytest.fixture
def mock_services(monkeypatch):
    calls = {"image": 0, "video": 0}

    def fake_image(user_photo, product_photo, prompt):
        calls["image"] += 1
        assert user_photo.exists() and product_photo.exists()
        assert "photorealistic" in prompt
        return make_photo_bytes(), "image/jpeg"

    def fake_video(image_path, prompt, output_path):
        calls["video"] += 1
        output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        return output_path

    monkeypatch.setattr(app_module.nanobanana_service, "generate_tryon_image", fake_image)
    monkeypatch.setattr(app_module.ltx_service, "generate_tryon_video", fake_video)
    return calls


def test_tryon_success_response_shape(mock_services):
    ring = next(i for i in client.get("/api/catalog").json() if i["type"] == "ring")
    resp = client.post(
        "/api/tryon",
        data={"item_id": ring["id"], "generate_video": "true"},
        files={"hand_photo": ("hand.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["item_id"] == ring["id"]
    assert data["category"] == "jewelry"
    assert data["item_type"] == "ring"
    assert data["photo_kind"] == "hand"
    assert data["image_url"].startswith("/outputs/")
    assert data["video_url"].startswith("/outputs/")
    assert data["video_error"] is None
    assert "photorealistic" in data["prompt"]
    # generated artifacts must actually be downloadable
    assert client.get(data["image_url"]).status_code == 200
    assert client.get(data["video_url"]).status_code == 200


def test_tryon_video_is_opt_in(mock_services):
    """Video generation costs real credits: it must NOT run unless requested."""
    ring = next(i for i in client.get("/api/catalog").json() if i["type"] == "ring")
    resp = client.post(
        "/api/tryon",
        data={"item_id": ring["id"]},  # generate_video omitted on purpose
        files={"hand_photo": ("hand.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["image_url"].startswith("/outputs/")
    assert data["video_url"] is None
    assert data["video_error"] is None
    assert mock_services["video"] == 0


def test_tryon_video_failure_still_returns_image(mock_services, monkeypatch):
    from backend.services.ltx_service import LTXError

    def failing_video(image_path, prompt, output_path):
        raise LTXError("The LTX account has insufficient video credits.")

    monkeypatch.setattr(app_module.ltx_service, "generate_tryon_video", failing_video)
    necklace = next(i for i in client.get("/api/catalog").json() if i["type"] == "necklace")
    resp = client.post(
        "/api/tryon",
        data={"item_id": necklace["id"], "generate_video": "true"},
        files={"face_photo": ("face.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["image_url"].startswith("/outputs/")
    assert data["video_url"] is None
    assert "credits" in data["video_error"]


def test_tryon_clothing_requires_body_photo():
    top = next(i for i in client.get("/api/catalog/clothing").json() if i["type"] == "top")
    # sending a face photo for a clothing item must fail with a clear message
    resp = client.post(
        "/api/tryon",
        data={"item_id": top["id"]},
        files={"face_photo": ("face.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 400
    assert "full-body photo" in resp.json()["detail"]


def test_tryon_clothing_success_uses_clothing_prompt(mock_services):
    dress = next(i for i in client.get("/api/catalog/clothing").json() if i["type"] == "dress")
    resp = client.post(
        "/api/tryon",
        data={"item_id": dress["id"]},
        files={"body_photo": ("body.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "clothing"
    assert data["item_type"] == "dress"
    assert data["photo_kind"] == "body"
    assert "garment" in data["prompt"].lower()  # clothing builder, not jewelry
    assert client.get(data["image_url"]).status_code == 200


def test_tryon_image_failure_returns_clean_502(mock_services, monkeypatch):
    from backend.services.nanobanana_service import NanoBananaError

    def failing_image(user_photo, product_photo, prompt):
        raise NanoBananaError("Nano Banana quota / rate limit reached for this API key.")

    monkeypatch.setattr(app_module.nanobanana_service, "generate_tryon_image", failing_image)
    ring = next(i for i in client.get("/api/catalog").json() if i["type"] == "ring")
    resp = client.post(
        "/api/tryon",
        data={"item_id": ring["id"]},
        files={"hand_photo": ("hand.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 502
    assert "Nano Banana" in resp.json()["detail"]
