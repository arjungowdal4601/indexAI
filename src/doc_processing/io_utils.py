"""Path, folder, page, JSON, and processing-state helpers."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .config import (
    ASSET_ROOT_SUFFIX,
    DOCLING_ASSET_FOLDER,
    FORMULA_IMAGE_FOLDER,
    PAGE_IMAGE_FOLDER,
    PAGE_MD_FOLDER,
    PICTURE_IMAGE_FOLDER,
    STITCHED_MARKDOWN_FILE,
    TABLE_IMAGE_FOLDER,
)


@dataclass(frozen=True)
class DoclingOutput:
    """Folders and files produced by raw Docling conversion."""

    docling_assets_dir: Path
    pages_md_dir: Path
    stitched_markdown_file: Path
    page_images_dir: Path
    picture_images_dir: Path
    table_images_dir: Path
    formula_images_dir: Path


def get_docling_output_paths(
    pdf_path: str | Path,
    output_root: str | Path | None = None,
) -> DoclingOutput:
    pdf_path = Path(pdf_path).resolve()
    asset_root = (
        Path(output_root).resolve()
        if output_root is not None
        else pdf_path.parent / f"{pdf_path.stem}{ASSET_ROOT_SUFFIX}"
    )
    docling_assets = asset_root / DOCLING_ASSET_FOLDER

    return DoclingOutput(
        docling_assets_dir=docling_assets,
        pages_md_dir=docling_assets / PAGE_MD_FOLDER,
        stitched_markdown_file=docling_assets / STITCHED_MARKDOWN_FILE,
        page_images_dir=docling_assets / PAGE_IMAGE_FOLDER,
        picture_images_dir=docling_assets / PICTURE_IMAGE_FOLDER,
        table_images_dir=docling_assets / TABLE_IMAGE_FOLDER,
        formula_images_dir=docling_assets / FORMULA_IMAGE_FOLDER,
    )


def recreate_docling_folders(output: DoclingOutput) -> None:
    if output.docling_assets_dir.exists():
        shutil.rmtree(output.docling_assets_dir)

    ensure_docling_folders(output)


def ensure_docling_folders(output: DoclingOutput) -> None:
    output.pages_md_dir.mkdir(parents=True, exist_ok=True)
    output.page_images_dir.mkdir(parents=True, exist_ok=True)
    output.picture_images_dir.mkdir(parents=True, exist_ok=True)
    output.table_images_dir.mkdir(parents=True, exist_ok=True)
    output.formula_images_dir.mkdir(parents=True, exist_ok=True)


def get_page_no_from_filename(path: Path) -> int:
    match = re.search(r"(\d+)", path.stem)
    if not match:
        raise ValueError(f"Cannot extract page number from file name: {path.name}")
    return int(match.group(1))


def read_page_markdowns(page_md_dir: str | Path) -> Dict[int, str]:
    page_md_dir = Path(page_md_dir)
    files = sorted(page_md_dir.glob("page_*.md"))

    if not files:
        raise FileNotFoundError(f"No page markdown files found in: {page_md_dir}")

    pages: Dict[int, str] = {}
    for file in files:
        page_no = get_page_no_from_filename(file)
        pages[page_no] = file.read_text(encoding="utf-8", errors="replace")

    return dict(sorted(pages.items()))


def write_json_file(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def processing_state_path(output_root: Path) -> Path:
    return output_root / "state" / "document_processing_state.json"


def write_processing_state(
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
    path = processing_state_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def infer_failed_page(output_root: Path | None, phase: str, error: Exception) -> int | None:
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


def count_completed_pages(output_root: Path | None, phase: str) -> int:
    if output_root is None:
        return 0
    folder = (
        output_root / "enriched_doc" / "pages_md"
        if phase == "enrichment"
        else output_root / "docling_assets" / "pages_md"
    )
    return len(list(folder.glob("page_*.md"))) if folder.exists() else 0


VISUAL_ASSET_FOLDERS = (
    TABLE_IMAGE_FOLDER,
    PICTURE_IMAGE_FOLDER,
    FORMULA_IMAGE_FOLDER,
)


def sorted_asset_paths(folder: Path, prefix: str) -> list[Path]:
    def asset_index(path: Path) -> int:
        match = re.search(r"(\d+)", path.stem)
        return int(match.group(1)) if match else 0

    return sorted(folder.glob(f"{prefix}-*.png"), key=asset_index)


def copy_visual_asset_folders(docling_assets_dir: Path, enriched_root: Path) -> None:
    for folder_name in VISUAL_ASSET_FOLDERS:
        source = docling_assets_dir / folder_name
        destination = enriched_root / folder_name

        if source.exists():
            shutil.copytree(source, destination, dirs_exist_ok=True)


def require_asset_count(kind: str, expected: int, actual: int, folder: Path) -> None:
    if expected != actual:
        raise RuntimeError(
            f"{kind} asset count mismatch: expected {expected}, found {actual} in {folder}"
        )
