"""FastAPI backend for the jewelry virtual try-on assignment.

Endpoints
---------
GET  /api/health    - health/config check
GET  /api/catalog   - jewelry catalog (loaded from backend/catalog/catalog.json)
POST /api/tryon     - multipart: item_id + face_photo and/or hand_photo
GET  /outputs/...   - generated images / videos (static)
GET  /catalog/...   - catalog product images (static)
GET  /              - the minimal frontend (static)

Run with:  uvicorn backend.app:app --reload
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from backend.config import (
    CATALOG_DIR,
    FRONTEND_DIR,
    OUTPUTS_DIR,
    UPLOADS_DIR,
    settings,
)
from backend.services import ltx_service, nanobanana_service, prompt_builder
from backend.services.ltx_service import LTXError
from backend.services.nanobanana_service import NanoBananaError

# ── Logging (structured key=value lines) ─────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='time=%(asctime)s level=%(levelname)s logger=%(name)s msg="%(message)s"',
)
logger = logging.getLogger("app")

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Jewelry Virtual Try-On", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}


def load_catalog() -> list[dict]:
    with open(CATALOG_DIR / "catalog.json", encoding="utf-8") as fh:
        return json.load(fh)["items"]


def get_item(item_id: str) -> dict:
    for item in load_catalog():
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"Unknown catalog item: {item_id}")


# ── Response models ───────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    app_env: str
    nanobanana_configured: bool
    ltx_configured: bool


class CatalogItemOut(BaseModel):
    id: str
    name: str
    type: str
    description: str
    image_url: str
    photo_kind: str  # which user photo this item needs: "face" or "hand"


class TryOnResponse(BaseModel):
    request_id: str
    item_id: str
    item_name: str
    jewelry_type: str
    photo_kind: str
    image_url: str
    video_url: Optional[str] = None
    video_error: Optional[str] = None
    prompt: str


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        nanobanana_configured=bool(settings.nanobanana_api_key),
        ltx_configured=bool(settings.ltx_api_key),
    )


@app.get("/api/catalog", response_model=list[CatalogItemOut])
def catalog() -> list[CatalogItemOut]:
    return [
        CatalogItemOut(
            id=item["id"],
            name=item["name"],
            type=item["type"],
            description=item["description"],
            image_url=f"/catalog/{item['image']}",
            photo_kind=prompt_builder.required_photo_kind(item["type"]),
        )
        for item in load_catalog()
    ]


def _validate_and_save_upload(upload: UploadFile, dest: Path) -> None:
    """Validate an uploaded photo and save a normalized JPEG copy."""
    if upload.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{upload.content_type}'. "
            "Please upload a JPEG, PNG or WebP photo.",
        )
    raw = upload.file.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=400,
            detail="Photo is too large (max 8 MB). Please upload a smaller image.",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded photo is empty.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.save(dest, "JPEG", quality=92)
    except UnidentifiedImageError:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a readable image.",
        )


@app.post("/api/tryon", response_model=TryOnResponse)
def tryon(
    item_id: str = Form(...),
    face_photo: Optional[UploadFile] = File(None),
    hand_photo: Optional[UploadFile] = File(None),
    # Video is opt-in: LTX bills per generated second, so the default must
    # never spend credits without the user explicitly asking for it.
    generate_video: bool = Form(False),
) -> TryOnResponse:
    item = get_item(item_id)
    jewelry_type = item["type"]
    photo_kind = prompt_builder.required_photo_kind(jewelry_type)

    # Type-aware photo selection: necklace/earrings -> face, ring/bracelet -> hand
    upload = face_photo if photo_kind == prompt_builder.PHOTO_KIND_FACE else hand_photo
    if upload is None or not upload.filename:
        raise HTTPException(
            status_code=400,
            detail=f"'{item['name']}' is a {jewelry_type}, which needs a "
            f"{photo_kind} photo. Please upload your {photo_kind} photo.",
        )

    request_id = uuid.uuid4().hex[:12]
    logger.info(
        "tryon start request_id=%s item=%s type=%s photo_kind=%s video=%s",
        request_id, item_id, jewelry_type, photo_kind, generate_video,
    )

    user_photo_path = UPLOADS_DIR / f"{request_id}_{photo_kind}.jpg"
    _validate_and_save_upload(upload, user_photo_path)

    product_photo_path = CATALOG_DIR / item["image"]
    if not product_photo_path.exists():
        raise HTTPException(status_code=500, detail="Catalog image is missing on disk.")

    # 1) Nano Banana try-on image
    prompt = prompt_builder.build_tryon_prompt(item)
    try:
        image_bytes, mime = nanobanana_service.generate_tryon_image(
            user_photo_path, product_photo_path, prompt
        )
    except NanoBananaError as exc:
        logger.error("tryon image_failed request_id=%s error=%s", request_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    ext = "png" if "png" in mime else "jpg"
    image_path = OUTPUTS_DIR / f"{request_id}_tryon.{ext}"
    image_path.write_bytes(image_bytes)
    logger.info("tryon image_saved request_id=%s path=%s", request_id, image_path.name)

    # 2) LTX video (optional; failure here does not void the image result)
    video_url: Optional[str] = None
    video_error: Optional[str] = None
    if generate_video:
        video_path = OUTPUTS_DIR / f"{request_id}_video.mp4"
        try:
            ltx_service.generate_tryon_video(
                image_path, prompt_builder.build_video_prompt(item), video_path
            )
            video_url = f"/outputs/{video_path.name}"
        except LTXError as exc:
            video_error = str(exc)
            logger.error("tryon video_failed request_id=%s error=%s", request_id, exc)

    logger.info(
        "tryon done request_id=%s image=%s video=%s",
        request_id, image_path.name, video_url or (f"error: {video_error}" if video_error else "skipped"),
    )
    return TryOnResponse(
        request_id=request_id,
        item_id=item["id"],
        item_name=item["name"],
        jewelry_type=jewelry_type,
        photo_kind=photo_kind,
        image_url=f"/outputs/{image_path.name}",
        video_url=video_url,
        video_error=video_error,
        prompt=prompt,
    )


# ── Static mounts (after API routes) ─────────────────────────────────────────

app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")
app.mount("/catalog", StaticFiles(directory=CATALOG_DIR), name="catalog")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
