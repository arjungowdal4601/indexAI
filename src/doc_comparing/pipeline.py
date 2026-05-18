"""High-level document processing pipeline orchestration."""

from __future__ import annotations

from pathlib import Path

from .config import PDF_PATH, TABLE_CONTINUITY_JSON_FILE
from .docling_converter import convert_pdf_with_docling
from .enrichment import enrich_document
from .table_detection import detect_table_continuity


def run_document_processing(pdf_path: str | Path = PDF_PATH) -> None:
    pdf_path = Path(pdf_path)

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

    docling_output = convert_pdf_with_docling(pdf_path)
    docling_assets_dir = docling_output.docling_assets_dir
    pages_md_dir = docling_output.pages_md_dir
    output_json_path = docling_assets_dir / TABLE_CONTINUITY_JSON_FILE

    table_payload = detect_table_continuity(
        page_md_dir=pages_md_dir,
        output_json_path=output_json_path,
    )
    enriched_output = enrich_document(docling_assets_dir)

    print("-" * 80)
    print("DOCUMENT PROCESSING COMPLETE")
    print(f"Docling assets folder: {docling_assets_dir}")
    print(f"Page markdown folder: {pages_md_dir}")
    print(f"Table continuity JSON: {output_json_path}")
    print(f"Multi-page table count: {table_payload['multi_page_table_count']}")
    print(f"Enriched page markdown folder: {enriched_output.pages_md_dir}")
    print(f"Readable markdown: {enriched_output.readable_markdown_file}")
    print("=" * 80)
