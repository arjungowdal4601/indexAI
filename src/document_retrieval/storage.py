"""File-backed storage helpers for vectorless document retrieval."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import PageContext, TopicEntry


def load_topic_index(topic_index_path: str | Path) -> list[TopicEntry]:
    path = Path(topic_index_path)
    if not path.exists():
        raise FileNotFoundError(f"Topic index not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Topic index root must be a list: {path}")
    return [TopicEntry.model_validate(_normalize_topic_payload(item)) for item in data]


def _normalize_topic_payload(item: object) -> object:
    if not isinstance(item, dict):
        return item
    normalized = dict(item)
    normalized.pop("keywords", None)
    normalized.setdefault("assets", [])
    return normalized


def page_markdown_path(pages_folder_path: str | Path, page_no: int) -> Path:
    return Path(pages_folder_path) / f"page_{int(page_no):04d}.md"


def normalize_page_numbers(pages: list[int]) -> list[int]:
    normalized = []
    seen = set()
    for page in pages:
        page_no = int(page)
        if page_no in seen:
            continue
        seen.add(page_no)
        normalized.append(page_no)
    return normalized


def missing_page_markdowns(
    pages_folder_path: str | Path,
    selected_pages: list[int],
) -> list[Path]:
    missing = []
    for page_no in normalize_page_numbers(selected_pages):
        path = page_markdown_path(pages_folder_path, page_no)
        if not path.exists():
            missing.append(path)
    return missing


def read_selected_page_markdowns(
    pages_folder_path: str | Path,
    selected_pages: list[int],
) -> list[PageContext]:
    contexts = []
    for page_no in normalize_page_numbers(selected_pages):
        path = page_markdown_path(pages_folder_path, page_no)
        markdown = path.read_text(encoding="utf-8", errors="replace")
        contexts.append(PageContext(page=page_no, path=path, markdown=markdown))
    return contexts
