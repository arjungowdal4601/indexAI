"""
Stage 1A: Docling-only PDF conversion.

This module converts a PDF page by page into raw Docling markdown and raw
Docling-generated assets. It does not generate descriptions, replace markdown
blocks, call an LLM, or write a manifest.
"""

from __future__ import annotations

import gc
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pypdf import PdfReader

from docling_core.types.doc import (
    DocItemLabel,
    FormulaItem,
    ImageRefMode,
    PictureItem,
    TableItem,
    TextItem,
)
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from .config import (
    ASSET_ROOT_SUFFIX,
    DOCLING_ASSET_FOLDER,
    FORMULA_IMAGE_FOLDER,
    IMAGE_PLACEHOLDER,
    IMAGES_SCALE,
    PAGE_IMAGE_FOLDER,
    PAGE_MD_FOLDER,
    PAGE_SEPARATOR_TEMPLATE,
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


def cleanup_memory() -> None:
    gc.collect()


def get_pdf_page_count(pdf_path: Path) -> int:
    with pdf_path.open("rb") as file:
        reader = PdfReader(file)
        return len(reader.pages)


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

    output.pages_md_dir.mkdir(parents=True, exist_ok=True)
    output.page_images_dir.mkdir(parents=True, exist_ok=True)
    output.picture_images_dir.mkdir(parents=True, exist_ok=True)
    output.table_images_dir.mkdir(parents=True, exist_ok=True)
    output.formula_images_dir.mkdir(parents=True, exist_ok=True)


def build_docling_converter(images_scale: float = IMAGES_SCALE) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.do_table_structure = True
    pipeline_options.do_formula_enrichment = True
    pipeline_options.generate_page_images = True
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_table_images = True
    pipeline_options.images_scale = float(images_scale)
    pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


def convert_pdf_page(
    converter: DocumentConverter,
    pdf_path: Path,
    page_no: int,
):
    return converter.convert(str(pdf_path), page_range=(page_no, page_no))


def export_page_markdown(doc: Any, page_no: int) -> str:
    return (
        doc.export_to_markdown(
            image_mode=ImageRefMode.PLACEHOLDER,
            image_placeholder=IMAGE_PLACEHOLDER,
            page_no=page_no,
        )
        or ""
    )


def save_page_images(doc: Any, output: DoclingOutput) -> None:
    for page_no, page in sorted(doc.pages.items()):
        page_image = getattr(page, "image", None)
        pil_image = getattr(page_image, "pil_image", None)
        if pil_image is None:
            continue

        image_path = output.page_images_dir / f"page-{page_no}.png"
        with image_path.open("wb") as file:
            pil_image.save(file, format="PNG")


def collect_raw_assets_from_doc(
    doc: Any,
    output: DoclingOutput,
    counters: Dict[str, int],
) -> None:
    for element, _level in doc.iterate_items():
        provenance = getattr(element, "prov", [])
        page_no = provenance[0].page_no if provenance else None
        if page_no is None:
            continue

        if isinstance(element, PictureItem):
            image = element.get_image(doc)
            if image is None:
                continue

            counters["picture"] += 1
            image_path = output.picture_images_dir / f"picture-{counters['picture']}.png"
            with image_path.open("wb") as file:
                image.save(file, "PNG")
            continue

        if isinstance(element, TableItem):
            image = element.get_image(doc)
            if image is None:
                continue

            counters["table"] += 1
            image_path = output.table_images_dir / f"table-{counters['table']}.png"
            with image_path.open("wb") as file:
                image.save(file, "PNG")
            continue

        is_formula = isinstance(element, FormulaItem) or (
            isinstance(element, TextItem)
            and getattr(element, "label", None) == DocItemLabel.FORMULA
        )
        if not is_formula:
            continue

        image = element.get_image(doc)
        if image is None:
            continue

        counters["formula"] += 1
        image_path = output.formula_images_dir / f"formula-{counters['formula']}.png"
        with image_path.open("wb") as file:
            image.save(file, "PNG")


def convert_pdf_with_docling(
    pdf_path: str | Path,
    page_range: Optional[Tuple[int, int]] = None,
    images_scale: float = IMAGES_SCALE,
    output_root: str | Path | None = None,
) -> DoclingOutput:
    """Convert a PDF into raw page-wise Docling markdown and raw assets."""
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output = get_docling_output_paths(pdf_path, output_root=output_root)
    recreate_docling_folders(output)

    if page_range is not None:
        start_page, end_page = page_range
    else:
        start_page, end_page = 1, get_pdf_page_count(pdf_path)

    start_page = int(start_page)
    end_page = int(end_page)

    converter = build_docling_converter(images_scale=images_scale)
    counters = {"picture": 0, "table": 0, "formula": 0}
    stitched_parts = []

    print(f"Docling conversion started: {pdf_path.name}")
    print(f"Pages: {start_page} to {end_page}")

    for page_no in range(start_page, end_page + 1):
        print(f"  - converting page {page_no}/{end_page}")

        conversion_result = convert_pdf_page(converter, pdf_path, page_no)
        doc = conversion_result.document

        save_page_images(doc, output)
        collect_raw_assets_from_doc(doc, output, counters)

        markdown = export_page_markdown(doc, page_no=page_no).strip()
        page_block = PAGE_SEPARATOR_TEMPLATE.format(page_no=page_no) + markdown + "\n"

        page_file = output.pages_md_dir / f"page_{page_no:04d}.md"
        page_file.write_text(page_block, encoding="utf-8")
        stitched_parts.append(page_block)

        cleanup_memory()

    output.stitched_markdown_file.write_text(
        "\n".join(stitched_parts).strip() + "\n",
        encoding="utf-8",
    )

    print("Docling conversion complete.")
    print(f"Docling assets: {output.docling_assets_dir}")
    print(f"Page markdown: {output.pages_md_dir}")
    print(f"Stitched markdown: {output.stitched_markdown_file}")

    return output
