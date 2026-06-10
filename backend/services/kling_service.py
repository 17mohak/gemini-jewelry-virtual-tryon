"""Kling AI image-to-video: animates the generated try-on image into a short
(3-10 s) video clip.

Kling's open API authenticates with a short-lived JWT signed from an
AccessKey / SecretKey pair (HS256). Flow:

1. ``POST /v1/videos/image2video``  -> returns a ``task_id``
2. poll ``GET /v1/videos/image2video/{task_id}`` until ``succeed``/``failed``
3. download the resulting MP4 to the local outputs folder
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

import httpx
import jwt

from backend.config import settings

logger = logging.getLogger("services.kling")

REQUEST_TIMEOUT = 60.0
POLL_INTERVAL_S = 10
MAX_WAIT_S = 8 * 60  # video generation regularly takes several minutes


class KlingError(Exception):
    """A Kling failure with a message that is safe to show to the end user."""


def _auth_header() -> dict:
    if not (settings.kling_access_key and settings.kling_secret_key):
        raise KlingError(
            "KLING_ACCESS_KEY / KLING_SECRET_KEY are not set. Add them to "
            "your .env file."
        )
    now = int(time.time())
    token = jwt.encode(
        {"iss": settings.kling_access_key, "exp": now + 1800, "nbf": now - 5},
        settings.kling_secret_key,
        algorithm="HS256",
        headers={"alg": "HS256", "typ": "JWT"},
    )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _friendly_api_error(status: int, payload: dict) -> KlingError:
    code = payload.get("code")
    message = payload.get("message", "")
    if code == 1003 or status == 401:
        return KlingError(
            "Kling rejected the credentials ('Authorization is not active'). "
            "This usually means the AccessKey/SecretKey pair is not activated "
            "for API use yet (no active API resource package / trial). Check "
            "the Kling developer console."
        )
    if code in (1102, 1103) or status == 429:
        return KlingError(
            "Kling account has no remaining credits or hit its rate limit. "
            "Top up / wait and try again."
        )
    return KlingError(f"Kling API error (HTTP {status}, code {code}): {message[:200]}")


def _post_task(image_path: Path, prompt: str) -> str:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    body = {
        "model_name": settings.kling_model,
        "image": image_b64,
        "prompt": prompt,
        "mode": "std",
        "duration": settings.kling_video_duration,
        "cfg_scale": 0.5,
    }
    url = f"{settings.kling_api_base}/v1/videos/image2video"
    resp = httpx.post(url, json=body, headers=_auth_header(), timeout=REQUEST_TIMEOUT)
    payload = _safe_json(resp)
    if resp.status_code != 200 or payload.get("code") != 0:
        logger.error("kling create_failed status=%d payload=%s", resp.status_code, str(payload)[:400])
        raise _friendly_api_error(resp.status_code, payload)
    task_id = payload["data"]["task_id"]
    logger.info("kling task_created task_id=%s model=%s", task_id, settings.kling_model)
    return task_id


def _poll_task(task_id: str) -> str:
    """Poll until the task finishes; return the video URL."""
    url = f"{settings.kling_api_base}/v1/videos/image2video/{task_id}"
    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        resp = httpx.get(url, headers=_auth_header(), timeout=REQUEST_TIMEOUT)
        payload = _safe_json(resp)
        if resp.status_code != 200 or payload.get("code") != 0:
            raise _friendly_api_error(resp.status_code, payload)
        data = payload.get("data", {})
        status = data.get("task_status")
        logger.info("kling poll task_id=%s status=%s", task_id, status)
        if status == "succeed":
            videos = data.get("task_result", {}).get("videos", [])
            if not videos:
                raise KlingError("Kling reported success but returned no video.")
            return videos[0]["url"]
        if status == "failed":
            raise KlingError(
                f"Kling video generation failed: "
                f"{data.get('task_status_msg', 'no reason given')}"
            )
        time.sleep(POLL_INTERVAL_S)
    raise KlingError(
        f"Kling video was not ready after {MAX_WAIT_S // 60} minutes; giving up."
    )


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {"code": None, "message": resp.text[:200]}


def generate_tryon_video(image_path: Path, prompt: str, output_path: Path) -> Path:
    """Generate a short video from the try-on image and save it locally."""
    try:
        task_id = _post_task(image_path, prompt)
        video_url = _poll_task(task_id)
        with httpx.stream("GET", video_url, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
    except KlingError:
        raise
    except httpx.TimeoutException as exc:
        raise KlingError("Kling request timed out. Please try again.") from exc
    except httpx.HTTPError as exc:
        raise KlingError(f"Could not reach the Kling API: {exc}") from exc
    logger.info("kling video_saved path=%s bytes=%d", output_path, output_path.stat().st_size)
    return output_path
