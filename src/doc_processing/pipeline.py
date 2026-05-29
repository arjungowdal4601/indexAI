"""High-level document processing pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import PDF_PATH
from .docling_converter import convert_pdf_with_docling
from .enrichment import enrich_document
from .io_utils import count_completed_pages, infer_failed_page, write_processing_state


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
        write_processing_state(
            output_root_path,
            document_id=processing_document_id,
            status="running",
            phase=phase,
            last_completed_page=count_completed_pages(output_root_path, phase),
        )
        docling_output = convert_pdf_with_docling(
            pdf_path,
            output_root=output_root_path,
            event_callback=event_callback,
            resume=resume,
        )
        docling_assets_dir = docling_output.docling_assets_dir
        pages_md_dir = docling_output.pages_md_dir

        phase = "enrichment"
        write_processing_state(
            output_root_path,
            document_id=processing_document_id,
            status="running",
            phase=phase,
            last_completed_page=count_completed_pages(output_root_path, phase),
        )
        enriched_output = enrich_document(
            docling_assets_dir,
            output_root=output_root_path / "enriched_doc" if output_root_path else None,
            event_callback=event_callback,
            resume=resume,
        )
    except Exception as exc:
        failed_page = infer_failed_page(output_root_path, phase, exc)
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
        write_processing_state(
            output_root_path,
            document_id=processing_document_id,
            status="failed",
            phase=phase,
            last_completed_page=count_completed_pages(output_root_path, phase),
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

    write_processing_state(
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
    print(f"Enriched page markdown folder: {enriched_output.pages_md_dir}")
    print(f"Readable markdown: {enriched_output.readable_markdown_file}")
    print("=" * 80)
