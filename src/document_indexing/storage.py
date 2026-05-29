"""File-backed storage helpers for document indexing."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from .schemas import (
    PageManifest,
    PageManifestEntry,
    PageMarkdown,
    PageWindow,
    ProcessingState,
    TopicAsset,
    TopicEntry,
    ValidationReport,
)

TOPIC_INDEX_FILE = "topic_index.json"
PROCESSING_STATE_FILE = "processing_state.json"
VALIDATION_REPORT_FILE = "validation_report.json"
REVISION_LOG_FILE = "revision_log.md"

PAGE_FILE_PATTERN = re.compile(r"(\d+)")
MARKDOWN_ASSET_PATTERN = re.compile(r"!\[(Figure|Table|Formula)\]\(([^)]+)\)")
ASSET_TYPE_BY_LABEL = {
    "Figure": "figure",
    "Table": "table",
    "Formula": "formula",
}


def page_number_from_path(path: Path) -> int:
    match = PAGE_FILE_PATTERN.search(path.stem)
    if not match:
        raise ValueError(f"Cannot extract page number from file name: {path.name}")
    return int(match.group(1))


def read_page_manifest(pages_folder_path: str | Path) -> PageManifest:
    pages_folder = Path(pages_folder_path)
    files = sorted(pages_folder.glob("page_*.md"), key=page_number_from_path)
    if not files:
        raise FileNotFoundError(f"No page markdown files found in: {pages_folder}")

    entries = [
        PageManifestEntry(page=page_number_from_path(path), path=path)
        for path in files
    ]
    page_numbers = [entry.page for entry in entries]
    total_pages = max(page_numbers)
    available = set(page_numbers)
    missing_pages = [
        page for page in range(min(page_numbers), total_pages + 1) if page not in available
    ]
    return PageManifest(total_pages=total_pages, pages=entries, missing_pages=missing_pages)


def read_page_window(
    manifest: PageManifest,
    target_page: int,
    current_topic_index: list[TopicEntry],
    include_next_page: bool = True,
) -> PageWindow:
    by_page = {entry.page: entry.path for entry in manifest.pages}

    target_path = by_page.get(target_page)
    if target_path is None:
        raise FileNotFoundError(f"Missing target page markdown for page {target_page}")

    next_page = None
    next_page_no = target_page + 1
    if include_next_page and next_page_no <= manifest.total_pages:
        path = by_page.get(next_page_no)
        if path is None:
            raise FileNotFoundError(
                f"Missing next context page markdown for page {next_page_no}"
            )
        next_page = PageMarkdown(
            page=next_page_no,
            markdown=path.read_text(encoding="utf-8"),
        )

    target_markdown = target_path.read_text(encoding="utf-8")
    return PageWindow(
        previous_page_topics=topics_for_page(current_topic_index, target_page - 1),
        target_page=PageMarkdown(
            page=target_page,
            markdown=target_markdown,
        ),
        target_page_assets=extract_page_assets(target_page, target_markdown),
        next_page=next_page,
    )


def topics_for_page(topics: list[TopicEntry], page_no: int) -> list[TopicEntry]:
    return [topic for topic in topics if page_no in topic.pages]


def _clean_asset_description(text: str, max_chars: int = 320) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    trimmed = cleaned[:max_chars].rsplit(" ", 1)[0].rstrip(" .,;:")
    return f"{trimmed}."


def _collect_asset_description(lines: list[str], start_index: int) -> str:
    collected: list[str] = []
    for line in lines[start_index:]:
        stripped = line.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith("## ") or MARKDOWN_ASSET_PATTERN.search(stripped):
            break
        collected.append(stripped)
        if len(" ".join(collected)) >= 280:
            break
    return _clean_asset_description(" ".join(collected))


def extract_page_assets(page: int, markdown: str) -> list[TopicAsset]:
    assets: list[TopicAsset] = []
    lines = markdown.splitlines()

    for index, line in enumerate(lines):
        match = MARKDOWN_ASSET_PATTERN.search(line)
        if match is None:
            continue
        label, path = match.groups()
        asset_type = ASSET_TYPE_BY_LABEL[label]
        description = _collect_asset_description(lines, index + 1)
        if not description:
            description = f"{asset_type.title()} asset on page {page}."
        assets.append(
            TopicAsset(
                page=page,
                type=asset_type,  # type: ignore[arg-type]
                path=path.strip(),
                description=description,
            )
        )

    return assets


def load_topic_index(topic_index_path: str | Path) -> list[TopicEntry]:
    path = Path(topic_index_path)
    if not path.exists():
        return []
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


def load_processing_state(
    output_dir: str | Path,
    document_id: str,
) -> ProcessingState:
    output_dir = Path(output_dir)
    path = output_dir / PROCESSING_STATE_FILE
    if not path.exists():
        return ProcessingState(document_id=document_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload.pop("main_window_size", None)
        payload.pop("context_window_size", None)
    state = ProcessingState.model_validate(payload)
    if state.document_id != document_id:
        raise ValueError(
            f"Processing state document_id mismatch: {state.document_id} != {document_id}"
        )
    return state


def _write_json_atomically(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    json.loads(tmp_path.read_text(encoding="utf-8"))
    os.replace(tmp_path, path)


def _dump_topics(topics: Iterable[TopicEntry]) -> list[dict]:
    return [topic.model_dump(mode="json") for topic in topics]


def write_topic_index(
    output_dir: str | Path,
    topics: list[TopicEntry],
    step_number: int,
) -> Path:
    output_dir = Path(output_dir)
    index_path = output_dir / TOPIC_INDEX_FILE
    if index_path.exists():
        backup_dir = output_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"topic_index_before_step_{step_number:04d}.json"
        backup_path.write_text(index_path.read_text(encoding="utf-8"), encoding="utf-8")

    _write_json_atomically(index_path, _dump_topics(topics))
    return index_path


def write_processing_state(
    output_dir: str | Path,
    state: ProcessingState,
) -> Path:
    path = Path(output_dir) / PROCESSING_STATE_FILE
    _write_json_atomically(path, state.model_dump(mode="json"))
    return path


def write_validation_report(
    output_dir: str | Path,
    report: ValidationReport,
) -> Path:
    path = Path(output_dir) / VALIDATION_REPORT_FILE
    _write_json_atomically(path, report.model_dump(mode="json"))
    return path


def append_revision_log(output_dir: str | Path, entry: str) -> Path:
    path = Path(output_dir) / REVISION_LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(entry.rstrip() + "\n\n")
    return path
