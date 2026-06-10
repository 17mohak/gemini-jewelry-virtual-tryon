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
    assert set(data) == {"status", "app_env", "gemini_configured", "kling_configured"}


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


def test_catalog_images_exist_on_disk_and_are_served():
    for item in client.get("/api/catalog").json():
        rel = item["image_url"].removeprefix("/catalog/")
        assert (CATALOG_DIR / rel).exists(), f"missing image for {item['id']}"
    first = client.get("/api/catalog").json()[0]
    assert client.get(first["image_url"]).status_code == 200


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


# ── Try-on success (Gemini + Kling mocked) ───────────────────────────────────

@pytest.fixture
def mock_services(monkeypatch):
    def fake_image(user_photo, product_photo, prompt):
        assert user_photo.exists() and product_photo.exists()
        assert "photorealistic" in prompt
        return make_photo_bytes(), "image/jpeg"

    def fake_video(image_path, prompt, output_path):
        output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        return output_path

    monkeypatch.setattr(app_module.gemini_service, "generate_tryon_image", fake_image)
    monkeypatch.setattr(app_module.kling_service, "generate_tryon_video", fake_video)


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
    assert data["jewelry_type"] == "ring"
    assert data["photo_kind"] == "hand"
    assert data["image_url"].startswith("/outputs/")
    assert data["video_url"].startswith("/outputs/")
    assert data["video_error"] is None
    assert "photorealistic" in data["prompt"]
    # generated artifacts must actually be downloadable
    assert client.get(data["image_url"]).status_code == 200
    assert client.get(data["video_url"]).status_code == 200


def test_tryon_video_failure_still_returns_image(mock_services, monkeypatch):
    from backend.services.kling_service import KlingError

    def failing_video(image_path, prompt, output_path):
        raise KlingError("Kling account has no remaining credits.")

    monkeypatch.setattr(app_module.kling_service, "generate_tryon_video", failing_video)
    necklace = next(i for i in client.get("/api/catalog").json() if i["type"] == "necklace")
    resp = client.post(
        "/api/tryon",
        data={"item_id": necklace["id"]},
        files={"face_photo": ("face.jpg", make_photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["image_url"].startswith("/outputs/")
    assert data["video_url"] is None
    assert "credits" in data["video_error"]
