"""Test bootstrap: redirect uploads/outputs to a temp directory.

This must run before ``backend.config`` is imported anywhere, because the
app's static mounts capture the directory paths at import time. pytest loads
conftest.py first, so setting the env vars here guarantees the whole suite
writes its mock artifacts to a throwaway location instead of polluting
``backend/uploads`` and ``backend/outputs``.
"""

import os
import tempfile
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="tryon-tests-"))
(_TEST_DATA_DIR / "uploads").mkdir()
(_TEST_DATA_DIR / "outputs").mkdir()

os.environ["TRYON_UPLOADS_DIR"] = str(_TEST_DATA_DIR / "uploads")
os.environ["TRYON_OUTPUTS_DIR"] = str(_TEST_DATA_DIR / "outputs")
