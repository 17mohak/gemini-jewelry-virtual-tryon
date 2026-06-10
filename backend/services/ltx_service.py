"""LTX 2.3 image-to-video: animates the generated try-on image into a short
video clip.

Uses the synchronous LTX Video API (https://docs.ltx.video): a single
``POST /v1/image-to-video`` with a Bearer key and the try-on image embedded as
a base64 data URI; the response body is the finished MP4. No polling needed.

Cost note: LTX bills per second of generated video (ltx-2-3-fast: $0.06/s at
1080p, 6 s minimum -> ~$0.36 per clip). This service therefore performs NO
automatic retries — a retry on an ambiguous failure could silently double the
spend. Failures are surfaced to the caller, and the caller decides.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from backend.config import settings

logger = logging.getLogger("services.ltx")

CONNECT_TIMEOUT = 30.0
# Sync generation holds the connection until the video is rendered.
READ_TIMEOUT = 600.0
MAX_IMAGE_SIDE = 1920  # data-URI inputs are capped at 7 MB encoded

PORTRAIT_RESOLUTION = "1080x1920"
LANDSCAPE_RESOLUTION = "1920x1080"


class LTXError(Exception):
    """An LTX failure with a message that is safe to show to the end user."""


def _image_data_uri(path: Path) -> tuple[str, str]:
    """Encode the image as a base64 data URI and pick the matching resolution.

    Returns ``(data_uri, resolution)`` where resolution is portrait or
    landscape 1080p depending on the source image's orientation (the ltx-2-3
    models support both 16:9 and 9:16).
    """
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        resolution = PORTRAIT_RESOLUTION if im.height > im.width else LANDSCAPE_RESOLUTION
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", resolution


def _friendly_error(status: int, payload: dict | None, raw: str) -> LTXError:
    message = ""
    if isinstance(payload, dict):
        message = (payload.get("error") or {}).get("message") or ""
    if status in (401, 403):
        return LTXError(
            f"LTX rejected the API key (HTTP {status}). Check LTX_API_KEY in "
            "your .env file."
        )
    if status == 402 or "credit" in message.lower() or "balance" in message.lower():
        return LTXError(
            "The LTX account has insufficient video credits. Video generation "
            "is intentionally budget-limited for this project — the try-on "
            "image above is unaffected."
        )
    if status == 429:
        return LTXError("LTX rate limit reached. Wait a moment and try again.")
    if status == 400:
        return LTXError(f"LTX rejected the request: {message or raw[:200]}")
    return LTXError(f"LTX API error (HTTP {status}): {message or raw[:200]}")


def generate_tryon_video(image_path: Path, prompt: str, output_path: Path) -> Path:
    """Generate a short video from the try-on image and save it locally.

    One request, one bill, no retries (see module docstring).
    """
    if not settings.ltx_api_key:
        raise LTXError("LTX_API_KEY is not set. Add it to your .env file.")

    image_uri, resolution = _image_data_uri(image_path)
    body = {
        "model": settings.ltx_model,
        "image_uri": image_uri,
        "prompt": prompt,
        "duration": settings.ltx_video_duration,
        "resolution": resolution,
        "fps": 24,
        "generate_audio": False,
        "camera_motion": "static",
    }
    logger.info(
        "ltx request model=%s duration=%ss resolution=%s image=%s prompt_chars=%d",
        settings.ltx_model, settings.ltx_video_duration, resolution,
        image_path.name, len(prompt),
    )

    try:
        resp = httpx.post(
            f"{settings.ltx_api_base}/v1/image-to-video",
            json=body,
            headers={"Authorization": f"Bearer {settings.ltx_api_key}"},
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        )
    except httpx.TimeoutException as exc:
        raise LTXError(
            "LTX video generation timed out; the clip may still have been "
            "billed — check the LTX dashboard before retrying."
        ) from exc
    except httpx.HTTPError as exc:
        raise LTXError(f"Could not reach the LTX API: {exc}") from exc

    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or "json" in content_type:
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        logger.error(
            "ltx error status=%d body=%s", resp.status_code, resp.text[:400]
        )
        raise _friendly_error(resp.status_code, payload, resp.text)

    output_path.write_bytes(resp.content)
    logger.info(
        "ltx video_saved path=%s bytes=%d", output_path.name, len(resp.content)
    )
    return output_path
