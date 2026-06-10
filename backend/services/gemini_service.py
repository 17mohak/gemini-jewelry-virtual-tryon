"""Google Gemini image generation: turns (user photo + product photo + prompt)
into a photorealistic try-on image.

Talks to the Gemini API over REST (``generativelanguage.googleapis.com``) so it
works with both standard AI Studio keys (``AIza...``) and Vertex AI
Express-mode keys (``AQ. ...``), which this endpoint also accepts.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from backend.config import settings

logger = logging.getLogger("services.gemini")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_TIMEOUT = 180.0  # image generation can take a while
MAX_IMAGE_SIDE = 1536  # downscale request images to keep payloads small


class GeminiError(Exception):
    """A Gemini failure with a message that is safe to show to the end user."""


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


def _friendly_http_error(status: int, body: str) -> GeminiError:
    if status == 429:
        return GeminiError(
            "Gemini quota / rate limit reached for this API key (HTTP 429). "
            "Free-tier image generation has very low limits - wait a minute "
            "and try again, or use a key from a project with image-generation "
            "quota."
        )
    if status in (401, 403):
        return GeminiError(
            "Gemini rejected the API key (HTTP %d). Check GEMINI_API_KEY in "
            "your .env file." % status
        )
    if status == 404:
        return GeminiError(
            f"Gemini model '{settings.gemini_model}' was not found for this "
            "key (HTTP 404). Set GEMINI_MODEL in .env to an image-capable "
            "model, e.g. gemini-2.5-flash-image."
        )
    return GeminiError(f"Gemini API error (HTTP {status}): {body[:300]}")


def generate_tryon_image(
    user_photo: Path, product_photo: Path, prompt: str
) -> tuple[bytes, str]:
    """Call Gemini and return ``(image_bytes, mime_type)`` of the try-on result.

    The part order matters: the prompt refers to the user photo as "Image 1"
    and the product photo as "Image 2", so they are attached in that order.
    """
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not set. Add it to your .env file.")

    url = f"{API_BASE}/models/{settings.gemini_model}:generateContent"
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
        "gemini request model=%s user_photo=%s product_photo=%s prompt_chars=%d",
        settings.gemini_model, user_photo.name, product_photo.name, len(prompt),
    )

    try:
        resp = httpx.post(
            url,
            json=body,
            headers={"x-goog-api-key": settings.gemini_api_key},
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.TimeoutException as exc:
        raise GeminiError("Gemini request timed out. Please try again.") from exc
    except httpx.HTTPError as exc:
        raise GeminiError(f"Could not reach the Gemini API: {exc}") from exc

    if resp.status_code != 200:
        logger.error("gemini http_error status=%d body=%s", resp.status_code, resp.text[:500])
        raise _friendly_http_error(resp.status_code, resp.text)

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback", {})
        logger.error("gemini no_candidates feedback=%s", feedback)
        raise GeminiError(
            "Gemini returned no result (the request may have been blocked by "
            f"safety filters: {feedback.get('blockReason', 'unknown reason')})."
        )

    text_notes = []
    for part in candidates[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData")
        if inline and inline.get("data"):
            mime = inline.get("mimeType", "image/png")
            logger.info("gemini success mime=%s", mime)
            return base64.b64decode(inline["data"]), mime
        if part.get("text"):
            text_notes.append(part["text"])

    logger.error("gemini no_image_part text=%s", " ".join(text_notes)[:300])
    raise GeminiError(
        "Gemini answered with text instead of an image"
        + (f": {' '.join(text_notes)[:200]}" if text_notes else ".")
    )
