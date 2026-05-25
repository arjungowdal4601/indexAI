"""Backend configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORAGE_ROOT = PROJECT_ROOT / "storage"
STORAGE_ROOT_ENV = "DOC_COMPARING_STORAGE_ROOT"
ARTIFACT_RETENTION_MODE = "standard"


def get_storage_root() -> Path:
    return Path(os.getenv(STORAGE_ROOT_ENV, str(DEFAULT_STORAGE_ROOT))).resolve()


def get_artifact_retention_mode() -> str:
    mode = ARTIFACT_RETENTION_MODE.strip().lower()
    if mode not in {"debug", "standard", "minimal"}:
        return "standard"
    return mode
