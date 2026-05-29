"""Standalone command line runner for the document indexing pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

if __package__ in (None, ""):
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from document_indexing.config import (
    DEFAULT_INCLUDE_NEXT_PAGE_CONTEXT,
    DEFAULT_PAGES_FOLDER,
    DEFAULT_TOPIC_INDEX_TOKEN_LIMIT,
    INDEXING_OUTPUT_FOLDER,
)
from document_indexing.pipeline import run_document_indexing
from document_indexing.schemas import IndexingOutput


def infer_asset_root(pages_folder_path: str | Path) -> Path:
    pages_folder = Path(pages_folder_path)
    if pages_folder.name == "pages_md" and pages_folder.parent.name == "enriched_doc":
        return pages_folder.parent.parent
    return pages_folder.parent


def infer_document_id(pages_folder_path: str | Path) -> str:
    asset_root = infer_asset_root(pages_folder_path)
    if asset_root.name.endswith("_doc_assets"):
        return asset_root.name[: -len("_doc_assets")]
    return asset_root.name


def default_output_folder(pages_folder_path: str | Path) -> Path:
    return infer_asset_root(pages_folder_path) / INDEXING_OUTPUT_FOLDER


def run_indexing_pipeline(
    pages_folder_path: str | Path = DEFAULT_PAGES_FOLDER,
    output_folder_path: str | Path | None = None,
    document_id: str | None = None,
    include_next_page_context: bool = DEFAULT_INCLUDE_NEXT_PAGE_CONTEXT,
    token_limit: int = DEFAULT_TOPIC_INDEX_TOKEN_LIMIT,
    event_callback: Callable[[str, str, str, int | None, int | None], None] | None = None,
) -> IndexingOutput:
    pages_folder = Path(pages_folder_path)
    output_folder = (
        Path(output_folder_path)
        if output_folder_path is not None
        else default_output_folder(pages_folder)
    )
    resolved_document_id = document_id or infer_document_id(pages_folder)

    return run_document_indexing(
        pages_folder_path=pages_folder,
        output_folder_path=output_folder,
        document_id=resolved_document_id,
        include_next_page_context=include_next_page_context,
        token_limit=token_limit,
        event_callback=event_callback,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a topic index from enriched page-wise Markdown files."
    )
    parser.add_argument(
        "--pages-folder",
        default=str(DEFAULT_PAGES_FOLDER),
        help="Folder containing enriched page_*.md files.",
    )
    parser.add_argument(
        "--output-folder",
        default=None,
        help="Folder where indexing_output files should be written.",
    )
    parser.add_argument(
        "--document-id",
        default=None,
        help="Document id stored in processing_state.json.",
    )
    parser.add_argument(
        "--no-next-page-context",
        dest="include_next_page_context",
        action="store_false",
        default=DEFAULT_INCLUDE_NEXT_PAGE_CONTEXT,
        help="Do not include the following page as extraction-only context.",
    )
    parser.add_argument(
        "--token-limit",
        type=int,
        default=DEFAULT_TOPIC_INDEX_TOKEN_LIMIT,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = run_indexing_pipeline(
        pages_folder_path=args.pages_folder,
        output_folder_path=args.output_folder,
        document_id=args.document_id,
        include_next_page_context=args.include_next_page_context,
        token_limit=args.token_limit,
    )

    print("DOCUMENT INDEXING COMPLETE")
    print(f"Topic index JSON: {output.topic_index_path}")
    print(f"Processing state JSON: {output.processing_state_path}")
    print(f"Revision log: {output.revision_log_path}")
    print(f"Validation report JSON: {output.validation_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
