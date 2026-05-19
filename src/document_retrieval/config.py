"""Configuration defaults for the vectorless document retrieval pipeline."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TOPIC_INDEX_PATH = (
    PROJECT_ROOT / "sample_doc_assets" / "indexing_output" / "topic_index.json"
)
DEFAULT_PAGES_FOLDER = PROJECT_ROOT / "sample_doc_assets" / "enriched_doc" / "pages_md"

DEFAULT_RETRIEVAL_MODEL = "gpt-5.4-mini"
DEFAULT_MAX_DIRECT_PAGES = 10
DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS = 70000


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
