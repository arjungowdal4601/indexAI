"""Deterministic agent guide generation for indexed document memory."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from .schemas import TopicEntry
from .storage import TOPIC_INDEX_FILE, load_topic_index

AGENT_MD_FILE = "agent.md"
DEFAULT_AGENT_MD_PATH = f"indexing_output/{AGENT_MD_FILE}"
DEFAULT_TOPIC_INDEX_PATH = f"indexing_output/{TOPIC_INDEX_FILE}"
DEFAULT_ENRICHED_PAGES_FOLDER = "enriched_doc/pages_md"
DEFAULT_PAGE_IMAGES_FOLDER = "docling_assets/page_images"


def _posix_path(value: object, default: str) -> str:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().replace("\\", "/")


def _clean_line(value: object, default: str = "unknown") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or default


def _one_line_description(description: str, max_chars: int = 220) -> str:
    text = _clean_line(description, default="No description available.")
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].rstrip(" .,;:")
    return f"{trimmed}."


def _format_pages(pages: Iterable[int]) -> str:
    ordered = sorted(set(int(page) for page in pages))
    if not ordered:
        return "none"

    ranges: list[str] = []
    start = ordered[0]
    previous = ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(f"{start}-{previous}" if start != previous else str(start))
        start = previous = page
    ranges.append(f"{start}-{previous}" if start != previous else str(start))
    return ", ".join(ranges)


def _load_manifest(manifest_path: str | Path | None) -> dict[str, Any]:
    if manifest_path is None:
        return {}
    path = Path(manifest_path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def _topic_lines(topic_index: Iterable[TopicEntry]) -> list[str]:
    lines: list[str] = []
    for topic in topic_index:
        lines.append(
            "- "
            f"{_clean_line(topic.topic)} | "
            f"pages {_format_pages(topic.pages)} | "
            f"{_one_line_description(topic.description)}"
        )
    if lines:
        return lines
    return [
        "- No indexed topics are available yet. Treat this as no direct indexed match."
    ]


def build_agent_memory_guide(
    *,
    document_id: str,
    filename: str | None,
    total_pages: int | None,
    topic_index: list[TopicEntry],
    manifest: dict[str, Any] | None = None,
) -> str:
    manifest = manifest or {}
    topic_index_path = _posix_path(
        manifest.get("topic_index_path"),
        DEFAULT_TOPIC_INDEX_PATH,
    )
    agent_md_path = _posix_path(
        manifest.get("agent_md_path"),
        DEFAULT_AGENT_MD_PATH,
    )
    enriched_pages_folder = _posix_path(
        manifest.get("enriched_pages_folder"),
        DEFAULT_ENRICHED_PAGES_FOLDER,
    )
    page_images_folder = _posix_path(
        manifest.get("page_images_folder"),
        DEFAULT_PAGE_IMAGES_FOLDER,
    )
    resolved_total_pages = total_pages or manifest.get("total_pages") or "unknown"

    lines = [
        "# Agent Memory Guide",
        "",
        "This document memory is an index-first guide for AI agents. Use it to locate the smallest useful page set before reading document content.",
        "",
        "## Document Identity",
        f"- document_id: {_clean_line(document_id)}",
        f"- filename: {_clean_line(filename)}",
        f"- total pages: {resolved_total_pages}",
        "",
        "## Core Rule",
        f"Read `{topic_index_path}` first.",
        "Do not read the whole document by default.",
        "",
        "## Retrieval Procedure",
        f"1. Read `{topic_index_path}`.",
        "2. Choose the smallest relevant topic set.",
        "3. Extract selected pages from the topic `pages` fields.",
        f"4. Read only `{enriched_pages_folder}/page_XXXX.md` for those pages.",
        "5. If the answer is still incomplete, expand to nearby or related indexed pages.",
        "6. Use page images only when visual confirmation is needed.",
        "",
        "## Paths",
        f"- topic index: `{topic_index_path}`",
        f"- agent guide: `{agent_md_path}`",
        f"- enriched pages folder: `{enriched_pages_folder}`",
        f"- page images folder: `{page_images_folder}`",
        "",
        "## Topic Navigation Summary",
        *_topic_lines(topic_index),
        "",
        "## Failure Handling",
        "If no topic matches, say no direct indexed match was found. Fall back to a broader scan of neighboring candidate pages or related indexed pages, not the full document immediately.",
        "",
    ]
    return "\n".join(lines)


def write_agent_memory_guide(
    *,
    output_dir: str | Path,
    document_id: str,
    original_filename: str | None = None,
    total_pages: int | None = None,
    topic_index_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> Path:
    output_dir = Path(output_dir)
    resolved_topic_index_path = Path(topic_index_path or output_dir / TOPIC_INDEX_FILE)
    manifest = _load_manifest(manifest_path)
    topics = load_topic_index(resolved_topic_index_path)
    if total_pages is None:
        manifest_total_pages = manifest.get("total_pages")
        if isinstance(manifest_total_pages, int):
            total_pages = manifest_total_pages
        else:
            indexed_pages = [
                page
                for topic in topics
                for page in topic.pages
            ]
            total_pages = max(indexed_pages, default=0) or None

    guide = build_agent_memory_guide(
        document_id=document_id,
        filename=original_filename,
        total_pages=total_pages,
        topic_index=topics,
        manifest=manifest,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / AGENT_MD_FILE
    tmp_path = output_dir / f"{AGENT_MD_FILE}.tmp"
    tmp_path.write_text(guide, encoding="utf-8")
    os.replace(tmp_path, path)
    return path
