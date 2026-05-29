"""
Stage 2: enrich raw Docling markdown with descriptions.

This module consumes Phase 1 outputs and writes a separate enriched document.
It does not mutate raw Docling assets.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import (
    PAGE_MD_FOLDER,
)
from .asset_registry import load_page_asset_registry, page_entries_by_number
from .enrichment_client import (
    DEFAULT_ENRICHMENT_MODEL,
    EnrichmentClient,
    OpenAIEnrichmentClient,
    TableDescriptionRequest,
    encode_image_to_base64,
    response_text,
)
from .io_utils import (
    VISUAL_ASSET_FOLDERS,
    copy_visual_asset_folders,
    read_page_markdowns,
    require_asset_count,
    sorted_asset_paths,
)
from .render_utils import (
    FORMULA_BLOCK_PATTERN,
    build_visual_markdown_block,
    count_formula_blocks,
    count_picture_placeholders,
    enrich_page_markdown_from_registry,
    replace_formula_blocks,
    replace_image_placeholders,
)

ENRICHED_DOC_FOLDER = "enriched_doc"
ENRICHED_PAGE_MD_FOLDER = "pages_md"
READABLE_MARKDOWN_FILE = "readable_processed_doc.md"


@dataclass(frozen=True)
class EnrichmentOutput:
    enriched_doc_dir: Path
    pages_md_dir: Path
    readable_markdown_file: Path


def enrich_document(
    docling_assets_dir: str | Path,
    client: Optional[EnrichmentClient] = None,
    output_root: Optional[str | Path] = None,
    event_callback=None,
    resume: bool = False,
) -> EnrichmentOutput:
    docling_assets_dir = Path(docling_assets_dir)
    pages_md_dir = docling_assets_dir / PAGE_MD_FOLDER
    enriched_root = (
        Path(output_root)
        if output_root is not None
        else docling_assets_dir.parent / ENRICHED_DOC_FOLDER
    )
    enriched_pages_dir = enriched_root / ENRICHED_PAGE_MD_FOLDER
    readable_markdown_file = enriched_root / READABLE_MARKDOWN_FILE

    if client is None:
        client = OpenAIEnrichmentClient()

    pages = read_page_markdowns(pages_md_dir)
    registry = load_page_asset_registry(docling_assets_dir)
    registry_pages = page_entries_by_number(registry)

    if enriched_root.exists() and not resume:
        shutil.rmtree(enriched_root)
    enriched_pages_dir.mkdir(parents=True, exist_ok=True)
    copy_visual_asset_folders(docling_assets_dir, enriched_root)

    stitched_parts: List[str] = []

    print("Document enrichment started.")
    for page_no, markdown in pages.items():
        print(f"  - enriching page {page_no}")
        page_file = enriched_pages_dir / f"page_{page_no:04d}.md"
        if resume and page_file.exists():
            stitched_parts.append(page_file.read_text(encoding="utf-8"))
            continue
        page_entry = registry_pages.get(page_no)
        if page_entry is None:
            raise RuntimeError(f"No page asset registry entry found for page {page_no}.")
        enriched_page = enrich_page_markdown_from_registry(
            markdown=markdown,
            page_no=page_no,
            page_entry=page_entry,
            docling_assets_dir=docling_assets_dir,
            client=client,
            event_callback=event_callback,
        )

        page_file.write_text(enriched_page, encoding="utf-8")
        stitched_parts.append(enriched_page)

    readable_markdown_file.write_text(
        "\n".join(part.strip() for part in stitched_parts).strip() + "\n",
        encoding="utf-8",
    )

    print(f"Document enrichment complete: {readable_markdown_file}")

    return EnrichmentOutput(
        enriched_doc_dir=enriched_root,
        pages_md_dir=enriched_pages_dir,
        readable_markdown_file=readable_markdown_file,
    )


__all__ = [
    "DEFAULT_ENRICHMENT_MODEL",
    "ENRICHED_DOC_FOLDER",
    "ENRICHED_PAGE_MD_FOLDER",
    "EnrichmentClient",
    "EnrichmentOutput",
    "FORMULA_BLOCK_PATTERN",
    "OpenAIEnrichmentClient",
    "READABLE_MARKDOWN_FILE",
    "TableDescriptionRequest",
    "VISUAL_ASSET_FOLDERS",
    "build_visual_markdown_block",
    "copy_visual_asset_folders",
    "count_formula_blocks",
    "count_picture_placeholders",
    "encode_image_to_base64",
    "enrich_document",
    "enrich_page_markdown_from_registry",
    "replace_formula_blocks",
    "replace_image_placeholders",
    "require_asset_count",
    "response_text",
    "sorted_asset_paths",
]
