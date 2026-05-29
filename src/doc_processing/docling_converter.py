"""
Stage 1A: Docling-only PDF conversion.

This module converts a PDF page by page into raw Docling markdown and raw
Docling-generated assets. It does not generate descriptions, replace markdown
blocks, call an LLM, or write a manifest.
"""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

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

from .asset_registry import (
    AssetRecord,
    build_page_registry_entry,
    has_page_registry_entry,
    upsert_page_registry_entry,
)
from .config import (
    IMAGE_PLACEHOLDER,
    IMAGES_SCALE,
    PAGE_SEPARATOR_TEMPLATE,
)
from .io_utils import (
    DoclingOutput,
    ensure_docling_folders,
    get_docling_output_paths,
    recreate_docling_folders,
)


def cleanup_memory() -> None:
    gc.collect()


def get_pdf_page_count(pdf_path: Path) -> int:
    with pdf_path.open("rb") as file:
        reader = PdfReader(file)
        return len(reader.pages)


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
) -> list[AssetRecord]:
    records: list[AssetRecord] = []
    local_counts: dict[tuple[int, str], int] = {}

    def next_local_index(page_no: int, kind: str) -> int:
        key = (page_no, kind)
        local_counts[key] = local_counts.get(key, 0) + 1
        return local_counts[key]

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
            records.append(
                AssetRecord(
                    kind="picture",
                    path=image_path.relative_to(output.docling_assets_dir).as_posix(),
                    source_page=page_no,
                    local_index=next_local_index(page_no, "picture"),
                    global_index=counters["picture"],
                )
            )
            continue

        if isinstance(element, TableItem):
            image = element.get_image(doc)
            if image is None:
                continue

            counters["table"] += 1
            image_path = output.table_images_dir / f"table-{counters['table']}.png"
            with image_path.open("wb") as file:
                image.save(file, "PNG")
            records.append(
                AssetRecord(
                    kind="table",
                    path=image_path.relative_to(output.docling_assets_dir).as_posix(),
                    source_page=page_no,
                    local_index=next_local_index(page_no, "table"),
                    global_index=counters["table"],
                )
            )
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
        records.append(
            AssetRecord(
                kind="formula",
                path=image_path.relative_to(output.docling_assets_dir).as_posix(),
                source_page=page_no,
                local_index=next_local_index(page_no, "formula"),
                global_index=counters["formula"],
            )
        )

    return records


def _existing_asset_count(folder: Path, prefix: str) -> int:
    count = 0
    for path in folder.glob(f"{prefix}-*.png"):
        try:
            count = max(count, int(path.stem.rsplit("-", 1)[1]))
        except ValueError:
            continue
    return count


def _write_stitched_markdown(output: DoclingOutput, start_page: int, end_page: int) -> None:
    parts = []
    for page_no in range(start_page, end_page + 1):
        page_file = output.pages_md_dir / f"page_{page_no:04d}.md"
        if page_file.exists():
            parts.append(page_file.read_text(encoding="utf-8").strip())
    output.stitched_markdown_file.write_text(
        "\n".join(part for part in parts if part).strip() + "\n",
        encoding="utf-8",
    )


def convert_pdf_with_docling(
    pdf_path: str | Path,
    page_range: Optional[Tuple[int, int]] = None,
    images_scale: float = IMAGES_SCALE,
    output_root: str | Path | None = None,
    event_callback: Callable[[str, str, str, int | None, int | None], None] | None = None,
    resume: bool = False,
) -> DoclingOutput:
    """Convert a PDF into raw page-wise Docling markdown and raw assets."""
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output = get_docling_output_paths(pdf_path, output_root=output_root)
    if resume:
        ensure_docling_folders(output)
    else:
        recreate_docling_folders(output)

    if page_range is not None:
        start_page, end_page = page_range
    else:
        start_page, end_page = 1, get_pdf_page_count(pdf_path)

    start_page = int(start_page)
    end_page = int(end_page)

    converter = None
    counters = {
        "picture": _existing_asset_count(output.picture_images_dir, "picture") if resume else 0,
        "table": _existing_asset_count(output.table_images_dir, "table") if resume else 0,
        "formula": _existing_asset_count(output.formula_images_dir, "formula") if resume else 0,
    }
    stitched_parts = []

    print(f"Docling conversion started: {pdf_path.name}")
    print(f"Pages: {start_page} to {end_page}")
    if event_callback is not None:
        event_callback(
            "document_processing",
            "processing_page",
            f"Processing page 0 of {end_page}",
            0,
            end_page,
        )

    for page_no in range(start_page, end_page + 1):
        page_file = output.pages_md_dir / f"page_{page_no:04d}.md"
        print(f"  - converting page {page_no}/{end_page}")
        if event_callback is not None:
            event_callback(
                "document_processing",
                "processing_page",
                f"Processing page {page_no} of {end_page}",
                page_no,
                end_page,
            )

        if resume and page_file.exists() and has_page_registry_entry(output.docling_assets_dir, page_no):
            stitched_parts.append(page_file.read_text(encoding="utf-8").strip())
            cleanup_memory()
            continue

        if converter is None:
            converter = build_docling_converter(images_scale=images_scale)
        conversion_result = convert_pdf_page(converter, pdf_path, page_no)
        doc = conversion_result.document

        save_page_images(doc, output)
        asset_records = collect_raw_assets_from_doc(doc, output, counters)

        markdown = export_page_markdown(doc, page_no=page_no).strip()
        page_block = PAGE_SEPARATOR_TEMPLATE.format(page_no=page_no) + markdown + "\n"

        page_file.write_text(page_block, encoding="utf-8")
        upsert_page_registry_entry(
            output.docling_assets_dir,
            build_page_registry_entry(
                page_no=page_no,
                markdown_path=page_file,
                docling_assets_dir=output.docling_assets_dir,
                markdown=page_block,
                assets=asset_records,
            ),
        )
        stitched_parts.append(page_block)

        cleanup_memory()

    if stitched_parts:
        output.stitched_markdown_file.write_text(
            "\n".join(part.strip() for part in stitched_parts).strip() + "\n",
            encoding="utf-8",
        )
    else:
        _write_stitched_markdown(output, start_page, end_page)

    print("Docling conversion complete.")
    print(f"Docling assets: {output.docling_assets_dir}")
    print(f"Page markdown: {output.pages_md_dir}")
    print(f"Stitched markdown: {output.stitched_markdown_file}")

    return output
