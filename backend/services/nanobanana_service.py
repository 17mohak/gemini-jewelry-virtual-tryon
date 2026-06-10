"""Nano Banana image generation: turns (user photo + product photo + prompt)
into a photorealistic try-on image.

Nano Banana is Google's image-editing model (API model id
``gemini-2.5-flash-image``), served over REST by the Generative Language API.
The service sends the edit prompt plus both images as inline data and returns
the generated image bytes.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from backend.config import settings

logger = logging.getLogger("services.nanobanana")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_TIMEOUT = 180.0  # image generation can take a while
MAX_IMAGE_SIDE = 1536  # downscale request images to keep payloads small
TRANSIENT_STATUS = {500, 502, 503, 504}
RETRY_DELAY_S = 4


class NanoBananaError(Exception):
    """A Nano Banana failure with a message safe to show to the end user."""


def _image_part(path: Path) -> dict:
    """Load an image, normalize orientation, downscale, and wrap as inlineData."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
    return {
        "inlineData": {
            "mimeType": "image/jpeg",
            "data": base64.b64encode(buf.getvalue()).decode("ascii"),
        }
    }


def _friendly_http_error(status: int, body: str) -> NanoBananaError:
    if status == 429:
        return NanoBananaError(
            "Nano Banana quota / rate limit reached for this API key "
            "(HTTP 429). Wait a minute and try again, or use a key whose "
            "project has image-generation quota."
        )
    if status in (401, 403):
        return NanoBananaError(
            f"Nano Banana rejected the API key (HTTP {status}). Check "
            "NANOBANANA_API_KEY in your .env file."
        )
    if status == 404:
        return NanoBananaError(
            f"Model '{settings.nanobanana_model}' was not found for this key "
            "(HTTP 404). Set NANOBANANA_MODEL in .env to an image-capable "
            "model, e.g. gemini-2.5-flash-image."
        )
    return NanoBananaError(f"Nano Banana API error (HTTP {status}): {body[:300]}")


def _post_with_retry(url: str, body: dict) -> httpx.Response:
    """POST once, retrying a single time on transient 5xx/network errors."""
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = httpx.post(
                url,
                json=body,
                headers={"x-goog-api-key": settings.nanobanana_api_key},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.TimeoutException as exc:
            raise NanoBananaError(
                "Nano Banana request timed out. Please try again."
            ) from exc
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("nanobanana network_error attempt=%d err=%s", attempt, exc)
        else:
            if resp.status_code in TRANSIENT_STATUS and attempt == 1:
                logger.warning(
                    "nanobanana transient_status attempt=%d status=%d",
                    attempt, resp.status_code,
                )
            else:
                return resp
        time.sleep(RETRY_DELAY_S)
    raise NanoBananaError(f"Could not reach the Nano Banana API: {last_exc}")


def generate_tryon_image(
    user_photo: Path, product_photo: Path, prompt: str
) -> tuple[bytes, str]:
    """Call Nano Banana and return ``(image_bytes, mime_type)`` of the result.

    Part order matters: the prompt refers to the user photo as "Image 1" and
    the product photo as "Image 2", so they are attached in that order.
    """
    if not settings.nanobanana_api_key:
        raise NanoBananaError(
            "NANOBANANA_API_KEY is not set. Add it to your .env file."
        )

    url = f"{API_BASE}/models/{settings.nanobanana_model}:generateContent"
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    _image_part(user_photo),
                    _image_part(product_photo),
                ],
            }
        ],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    logger.info(
        "nanobanana request model=%s user_photo=%s product_photo=%s prompt_chars=%d",
        settings.nanobanana_model, user_photo.name, product_photo.name, len(prompt),
    )

    resp = _post_with_retry(url, body)
    if resp.status_code != 200:
        logger.error(
            "nanobanana http_error status=%d body=%s", resp.status_code, resp.text[:500]
        )
        raise _friendly_http_error(resp.status_code, resp.text)

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback", {})
        logger.error("nanobanana no_candidates feedback=%s", feedback)
        raise NanoBananaError(
            "Nano Banana returned no result (the request may have been blocked "
            f"by safety filters: {feedback.get('blockReason', 'unknown reason')})."
        )

    text_notes = []
    for part in candidates[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData")
        if inline and inline.get("data"):
            mime = inline.get("mimeType", "image/png")
            logger.info("nanobanana success mime=%s", mime)
            return base64.b64decode(inline["data"]), mime
        if part.get("text"):
            text_notes.append(part["text"])

    logger.error("nanobanana no_image_part text=%s", " ".join(text_notes)[:300])
    raise NanoBananaError(
        "Nano Banana answered with text instead of an image"
        + (f": {' '.join(text_notes)[:200]}" if text_notes else ".")
    )
