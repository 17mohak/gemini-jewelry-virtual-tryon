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

    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash-image")
    )

    kling_access_key: str = field(default_factory=lambda: os.getenv("KLING_ACCESS_KEY", ""))
    kling_secret_key: str = field(default_factory=lambda: os.getenv("KLING_SECRET_KEY", ""))
    kling_model: str = field(default_factory=lambda: os.getenv("KLING_MODEL", "kling-v1"))
    kling_api_base: str = field(
        default_factory=lambda: os.getenv(
            "KLING_API_BASE", "https://api-singapore.klingai.com"
        )
    )
    kling_video_duration: str = field(
        default_factory=lambda: os.getenv("KLING_VIDEO_DURATION", "5")
    )

    max_upload_bytes: int = 8 * 1024 * 1024  # 8 MB


settings = Settings()
