"""Configuration defaults for the standalone document indexing pipeline."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PAGES_FOLDER = PROJECT_ROOT / "sample_doc_assets" / "enriched_doc" / "pages_md"
INDEXING_OUTPUT_FOLDER = "indexing_output"

DEFAULT_MAIN_WINDOW_SIZE = 3
DEFAULT_CONTEXT_WINDOW_SIZE = 2
DEFAULT_TOPIC_INDEX_TOKEN_LIMIT = 80000
