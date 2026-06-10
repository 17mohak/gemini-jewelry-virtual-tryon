"""Central configuration. All secrets come from environment variables (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repository root regardless of the working directory.
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

BACKEND_DIR = Path(__file__).resolve().parent
CATALOG_DIR = BACKEND_DIR / "catalog"
UPLOADS_DIR = BACKEND_DIR / "uploads"
OUTPUTS_DIR = BACKEND_DIR / "outputs"
FRONTEND_DIR = ROOT_DIR / "frontend"


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "local"))

    # ── Nano Banana (image try-on) ────────────────────────────────────────
    # Nano Banana is Google's image-editing model family, served by the
    # Generative Language API. The newer generation (gemini-3.1-flash-image)
    # is the default: the older gemini-2.5-flash-image deterministically
    # refuses some clothing edits on real-person photos (finishReason
    # IMAGE_OTHER) that 3.1 handles correctly.
    nanobanana_api_key: str = field(
        default_factory=lambda: os.getenv("NANOBANANA_API_KEY", "")
    )
    nanobanana_model: str = field(
        default_factory=lambda: os.getenv("NANOBANANA_MODEL", "gemini-3.1-flash-image")
    )

    # ── LTX 2.3 (image -> short video) ────────────────────────────────────
    ltx_api_key: str = field(default_factory=lambda: os.getenv("LTX_API_KEY", ""))
    ltx_model: str = field(default_factory=lambda: os.getenv("LTX_MODEL", "ltx-2-3-fast"))
    ltx_api_base: str = field(
        default_factory=lambda: os.getenv("LTX_API_BASE", "https://api.ltx.video")
    )
    # Billed per second of output; 6 s is the shortest the API allows.
    ltx_video_duration: int = field(
        default_factory=lambda: int(os.getenv("LTX_VIDEO_DURATION", "6"))
    )

    max_upload_bytes: int = 8 * 1024 * 1024  # 8 MB


settings = Settings()
