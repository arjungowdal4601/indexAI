"""High-level document processing pipeline orchestration."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import PDF_PATH, TABLE_CONTINUITY_JSON_FILE
from .docling_converter import convert_pdf_with_docling
from .enrichment import enrich_document
from .table_detection import detect_table_continuity


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _state_path(output_root: Path) -> Path:
    return output_root / "state" / "document_processing_state.json"


def _write_processing_state(
    output_root: Path | None,
    *,
    document_id: str,
    status: str,
    phase: str,
    last_completed_page: int = 0,
    failed_pages: list[dict] | None = None,
    error: Exception | None = None,
) -> None:
    if output_root is None:
        return
    payload = {
        "document_id": document_id,
        "status": status,
        "last_completed_page": int(last_completed_page),
        "failed_pages": failed_pages or [],
        "phase": phase,
        "updated_at": _utc_now(),
    }
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)
    path = _state_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _infer_failed_page(output_root: Path | None, phase: str, error: Exception) -> int | None:
    text = str(error)
    match = re.search(r"page\s+(\d+)", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    if output_root is None:
        return None
    if phase == "enrichment":
        raw_pages = sorted((output_root / "docling_assets" / "pages_md").glob("page_*.md"))
        enriched_pages = {path.name for path in (output_root / "enriched_doc" / "pages_md").glob("page_*.md")}
        for path in raw_pages:
            if path.name not in enriched_pages:
                page_match = re.search(r"(\d+)", path.stem)
                return int(page_match.group(1)) if page_match else None
    return None


def _count_completed_pages(output_root: Path | None, phase: str) -> int:
    if output_root is None:
        return 0
    folder = (
        output_root / "enriched_doc" / "pages_md"
        if phase == "enrichment"
        else output_root / "docling_assets" / "pages_md"
    )
    return len(list(folder.glob("page_*.md"))) if folder.exists() else 0


def run_document_processing(
    pdf_path: str | Path = PDF_PATH,
    output_root: str | Path | None = None,
    event_callback: Callable[[str, str, str, int | None, int | None], None] | None = None,
    resume: bool = False,
    document_id: str | None = None,
) -> None:
    pdf_path = Path(pdf_path)
    output_root_path = Path(output_root) if output_root is not None else None
    processing_document_id = document_id or pdf_path.stem

    print("=" * 80)
    print("DOCUMENT PROCESSING PIPELINE")
    print("=" * 80)
    print(f"PDF_PATH: {pdf_path}")
    print("Phase 1 LLM usage: False")
    print("Phase 2 OpenAI enrichment: True")
    print("-" * 80)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}\n"
            "Put your PDF in this folder and update PDF_PATH in config.py."
        )

    phase = "docling_conversion"
    try:
        _write_processing_state(
            output_root_path,
            document_id=processing_document_id,
            status="running",
            phase=phase,
            last_completed_page=_count_completed_pages(output_root_path, phase),
        )
        docling_output = convert_pdf_with_docling(
            pdf_path,
            output_root=output_root_path,
            event_callback=event_callback,
            resume=resume,
        )
        docling_assets_dir = docling_output.docling_assets_dir
        pages_md_dir = docling_output.pages_md_dir
        output_json_path = docling_assets_dir / TABLE_CONTINUITY_JSON_FILE

        phase = "table_detection"
        _write_processing_state(
            output_root_path,
            document_id=processing_document_id,
            status="running",
            phase=phase,
            last_completed_page=_count_completed_pages(output_root_path, "docling_conversion"),
        )
        table_payload = detect_table_continuity(
            page_md_dir=pages_md_dir,
            output_json_path=output_json_path,
        )

        phase = "enrichment"
        _write_processing_state(
            output_root_path,
            document_id=processing_document_id,
            status="running",
            phase=phase,
            last_completed_page=_count_completed_pages(output_root_path, phase),
        )
        enriched_output = enrich_document(
            docling_assets_dir,
            output_root=output_root_path / "enriched_doc" if output_root_path else None,
            event_callback=event_callback,
            resume=resume,
        )
    except Exception as exc:
        failed_page = _infer_failed_page(output_root_path, phase, exc)
        failed_pages = []
        if failed_page is not None:
            failed_pages.append(
                {
                    "page": failed_page,
                    "phase": phase,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
        _write_processing_state(
            output_root_path,
            document_id=processing_document_id,
            status="failed",
            phase=phase,
            last_completed_page=_count_completed_pages(output_root_path, phase),
            failed_pages=failed_pages,
            error=exc,
        )
        raise

    if event_callback is not None:
        total_pages = len(list(enriched_output.pages_md_dir.glob("page_*.md")))
        event_callback(
            "document_processing",
            "processing_page",
            f"Processing page {total_pages} of {total_pages}",
            total_pages,
            total_pages,
        )

    _write_processing_state(
        output_root_path,
        document_id=processing_document_id,
        status="completed",
        phase="completed",
        last_completed_page=len(list(enriched_output.pages_md_dir.glob("page_*.md"))),
    )

    print("-" * 80)
    print("DOCUMENT PROCESSING COMPLETE")
    print(f"Docling assets folder: {docling_assets_dir}")
    print(f"Page markdown folder: {pages_md_dir}")
    print(f"Table continuity JSON: {output_json_path}")
    print(f"Multi-page table count: {table_payload['multi_page_table_count']}")
    print(f"Enriched page markdown folder: {enriched_output.pages_md_dir}")
    print(f"Readable markdown: {enriched_output.readable_markdown_file}")
    print("=" * 80)
