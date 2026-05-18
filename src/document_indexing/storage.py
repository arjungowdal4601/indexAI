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
    TopicEntry,
    ValidationReport,
)

TOPIC_INDEX_FILE = "topic_index.json"
PROCESSING_STATE_FILE = "processing_state.json"
VALIDATION_REPORT_FILE = "validation_report.json"
REVISION_LOG_FILE = "revision_log.md"

PAGE_FILE_PATTERN = re.compile(r"(\d+)")


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
    start_page: int,
    main_window_size: int,
    context_window_size: int,
) -> PageWindow:
    by_page = {entry.page: entry.path for entry in manifest.pages}
    main_pages = []
    context_pages = []

    main_end = min(start_page + main_window_size - 1, manifest.total_pages)
    context_end = min(main_end + context_window_size, manifest.total_pages)

    for page_no in range(start_page, main_end + 1):
        path = by_page.get(page_no)
        if path is None:
            raise FileNotFoundError(f"Missing main page markdown for page {page_no}")
        main_pages.append(
            PageMarkdown(page=page_no, markdown=path.read_text(encoding="utf-8"))
        )

    for page_no in range(main_end + 1, context_end + 1):
        path = by_page.get(page_no)
        if path is None:
            raise FileNotFoundError(f"Missing context page markdown for page {page_no}")
        context_pages.append(
            PageMarkdown(page=page_no, markdown=path.read_text(encoding="utf-8"))
        )

    return PageWindow(main_pages=main_pages, context_pages=context_pages)


def load_topic_index(topic_index_path: str | Path) -> list[TopicEntry]:
    path = Path(topic_index_path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Topic index root must be a list: {path}")
    return [TopicEntry.model_validate(item) for item in data]


def load_processing_state(
    output_dir: str | Path,
    document_id: str,
    main_window_size: int,
    context_window_size: int,
) -> ProcessingState:
    output_dir = Path(output_dir)
    path = output_dir / PROCESSING_STATE_FILE
    if not path.exists():
        return ProcessingState(
            document_id=document_id,
            main_window_size=main_window_size,
            context_window_size=context_window_size,
        )
    state = ProcessingState.model_validate_json(path.read_text(encoding="utf-8"))
    if state.document_id != document_id:
        raise ValueError(
            f"Processing state document_id mismatch: {state.document_id} != {document_id}"
        )
    if (
        state.main_window_size != main_window_size
        or state.context_window_size != context_window_size
    ):
        raise ValueError("Processing state window sizes do not match this run.")
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
