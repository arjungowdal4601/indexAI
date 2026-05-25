"""
Stage 2: enrich raw Docling markdown with descriptions.

This module consumes Phase 1 outputs and writes a separate enriched document.
It does not mutate raw Docling assets or the table-continuity JSON.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Protocol, Tuple

from backend.services.retry_utils import run_with_retries

from .config import (
    FORMULA_IMAGE_FOLDER,
    IMAGE_PLACEHOLDER,
    PAGE_MD_FOLDER,
    PICTURE_IMAGE_FOLDER,
    TABLE_IMAGE_FOLDER,
)
from .prompts import (
    FORMULA_PROMPT,
    PICTURE_PROMPT,
    build_table_context,
    build_table_prompt,
)
from .table_detection import (
    extract_all_table_blocks,
    find_table_line_ranges,
    group_logical_tables,
    read_page_markdowns,
)

ENRICHED_DOC_FOLDER = "enriched_doc"
ENRICHED_PAGE_MD_FOLDER = "pages_md"
READABLE_MARKDOWN_FILE = "readable_processed_doc.md"
DEFAULT_ENRICHMENT_MODEL = "gpt-5.4-mini"
VISUAL_ASSET_FOLDERS = (
    TABLE_IMAGE_FOLDER,
    PICTURE_IMAGE_FOLDER,
    FORMULA_IMAGE_FOLDER,
)

FORMULA_BLOCK_PATTERN = re.compile(
    r"(?s)"
    r"(\$\$.*?\$\$"
    r"|\\\[.*?\\\]"
    r"|\\begin\{equation\*?\}.*?\\end\{equation\*?\}"
    r"|\\begin\{align\*?\}.*?\\end\{align\*?\}"
    r"|\\begin\{gather\*?\}.*?\\end\{gather\*?\}"
    r"|\\begin\{multline\*?\}.*?\\end\{multline\*?\})"
)


@dataclass(frozen=True)
class EnrichmentOutput:
    enriched_doc_dir: Path
    pages_md_dir: Path
    readable_markdown_file: Path


@dataclass(frozen=True)
class TableFragment:
    table_id: str
    page_no: int
    table_index_on_page: int
    block_id: str
    raw_markdown: str
    image_path: Path
    is_multi_page: bool
    pages: List[int]


@dataclass(frozen=True)
class TableDescriptionRequest:
    table_id: str
    page_no: int
    pages: List[int]
    current_markdown: str
    current_image_path: Path
    previous_markdown: Optional[str] = None
    previous_image_path: Optional[Path] = None


class EnrichmentClient(Protocol):
    def describe_table(self, request: TableDescriptionRequest) -> str:
        ...

    def describe_image(self, image_path: Path) -> str:
        ...

    def describe_formula(self, image_path: Path, formula_markdown: str) -> str:
        ...


def encode_image_to_base64(image_path: Path) -> str:
    with image_path.open("rb") as file:
        return base64.b64encode(file.read()).decode("utf-8")


def response_text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


class OpenAIEnrichmentClient:
    def __init__(self, model: Optional[str] = None):
        try:
            from dotenv import load_dotenv
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Document enrichment requires python-dotenv and langchain-openai. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for document enrichment. "
                "Phase 1 artifacts are available; set OPENAI_API_KEY and rerun python main.py."
            )

        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model
            or os.getenv("DOC_ENRICHMENT_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_ENRICHMENT_MODEL,
        )

    def _image_base64(self, image_path: Path) -> str:
        return encode_image_to_base64(image_path)

    def describe_table(self, request: TableDescriptionRequest) -> str:
        table_context = build_table_context(
            table_id=request.table_id,
            page_no=request.page_no,
            pages=request.pages,
            current_markdown=request.current_markdown,
            previous_markdown=request.previous_markdown,
        )
        previous_image_base64 = (
            self._image_base64(request.previous_image_path)
            if request.previous_image_path
            else None
        )
        current_image_base64 = self._image_base64(request.current_image_path)
        prompt = build_table_prompt(
            include_previous_image=bool(previous_image_base64),
            include_current_image=True,
        )
        inputs = {
            "table_context": table_context,
            "current_image_base64": current_image_base64,
        }
        if previous_image_base64 is not None:
            inputs["previous_image_base64"] = previous_image_base64

        chain = prompt | self.llm
        response = chain.invoke(inputs)
        return response_text(response)

    def describe_image(self, image_path: Path) -> str:
        chain = PICTURE_PROMPT | self.llm
        response = chain.invoke({"image_base64": self._image_base64(image_path)})
        return response_text(response)

    def describe_formula(self, image_path: Path, formula_markdown: str) -> str:
        chain = FORMULA_PROMPT | self.llm
        response = chain.invoke(
            {
                "image_base64": self._image_base64(image_path),
                "formula_markdown": formula_markdown,
            }
        )
        return response_text(response)


def sorted_asset_paths(folder: Path, prefix: str) -> List[Path]:
    def asset_index(path: Path) -> int:
        match = re.search(r"(\d+)", path.stem)
        return int(match.group(1)) if match else 0

    return sorted(folder.glob(f"{prefix}-*.png"), key=asset_index)


def build_visual_markdown_block(label: str, image_path: Path, description: str) -> str:
    description = description.strip()
    relative_path = f"{image_path.parent.name}/{image_path.name}".replace("\\", "/")
    return f"![{label}]({relative_path})\n\n{description}".strip()


def copy_visual_asset_folders(docling_assets_dir: Path, enriched_root: Path) -> None:
    for folder_name in VISUAL_ASSET_FOLDERS:
        source = docling_assets_dir / folder_name
        destination = enriched_root / folder_name

        if source.exists():
            shutil.copytree(source, destination, dirs_exist_ok=True)


def count_picture_placeholders(pages: Dict[int, str]) -> int:
    return sum(markdown.count(IMAGE_PLACEHOLDER) for markdown in pages.values())


def count_formula_blocks(pages: Dict[int, str]) -> int:
    return sum(1 for markdown in pages.values() for _ in FORMULA_BLOCK_PATTERN.finditer(markdown))


def require_asset_count(kind: str, expected: int, actual: int, folder: Path) -> None:
    if expected != actual:
        raise RuntimeError(
            f"{kind} asset count mismatch: expected {expected}, found {actual} in {folder}"
        )


def build_table_fragment_index(
    docling_assets_dir: str | Path,
    pages: Dict[int, str],
    table_images: List[Path],
) -> Dict[Tuple[int, int], TableFragment]:
    docling_assets_dir = Path(docling_assets_dir)
    blocks = extract_all_table_blocks(pages)
    require_asset_count(
        kind="Table",
        expected=len(blocks),
        actual=len(table_images),
        folder=docling_assets_dir / TABLE_IMAGE_FOLDER,
    )

    logical_tables = group_logical_tables(blocks)

    table_by_block_id = {}
    for table in logical_tables:
        for fragment in table.fragments:
            table_by_block_id[fragment["block_id"]] = table

    fragments: Dict[Tuple[int, int], TableFragment] = {}
    sorted_blocks = sorted(blocks, key=lambda block: (block.page_no, block.block_index_on_page))
    for image_index, block in enumerate(sorted_blocks):
        logical_table = table_by_block_id[block.block_id]
        fragments[(block.page_no, block.block_index_on_page)] = TableFragment(
            table_id=logical_table.table_id,
            page_no=block.page_no,
            table_index_on_page=block.block_index_on_page,
            block_id=block.block_id,
            raw_markdown=block.raw_markdown,
            image_path=table_images[image_index],
            is_multi_page=logical_table.is_multi_page,
            pages=logical_table.pages,
        )

    return fragments


def replace_tables(
    markdown: str,
    page_no: int,
    table_fragments: Dict[Tuple[int, int], TableFragment],
    client: EnrichmentClient,
    previous_by_table_id: Dict[str, TableFragment],
    event_callback=None,
) -> str:
    lines = markdown.splitlines()
    ranges = find_table_line_ranges(lines)
    if not ranges:
        return markdown

    output_lines: List[str] = []
    cursor = 0

    for table_index, (start, end) in enumerate(ranges, start=1):
        output_lines.extend(lines[cursor:start])
        fragment = table_fragments.get((page_no, table_index))
        if not fragment:
            raise RuntimeError(f"No table fragment found for page {page_no}, table {table_index}.")

        previous = previous_by_table_id.get(fragment.table_id) if fragment.is_multi_page else None
        request = TableDescriptionRequest(
            table_id=fragment.table_id,
            page_no=page_no,
            pages=fragment.pages,
            current_markdown=fragment.raw_markdown,
            current_image_path=fragment.image_path,
            previous_markdown=previous.raw_markdown if previous else None,
            previous_image_path=previous.image_path if previous else None,
        )
        if event_callback is not None:
            event_callback(
                "document_processing",
                "waiting_for_llm",
                f"Waiting for LLM response for page {page_no} / table {table_index}",
                page_no,
                None,
            )
        description = run_with_retries(
            lambda: client.describe_table(request),
            on_retry=lambda attempt, exc: event_callback(
                "document_processing",
                "retry",
                f"Retrying LLM call for page {page_no}, attempt {attempt}: {type(exc).__name__}: {exc}",
                page_no,
                None,
            )
            if event_callback is not None
            else None,
        ).strip()
        output_lines.append(
            build_visual_markdown_block("Table", fragment.image_path, description)
        )

        if fragment.is_multi_page:
            previous_by_table_id[fragment.table_id] = fragment

        cursor = end + 1

    output_lines.extend(lines[cursor:])
    return "\n".join(output_lines)


def replace_image_placeholders(
    markdown: str,
    image_paths: Iterator[Path],
    client: EnrichmentClient,
    page_no: int | None = None,
    event_callback=None,
) -> str:
    output_parts: List[str] = []
    cursor = 0

    while True:
        position = markdown.find(IMAGE_PLACEHOLDER, cursor)
        if position == -1:
            output_parts.append(markdown[cursor:])
            break

        output_parts.append(markdown[cursor:position])
        try:
            image_path = next(image_paths)
        except StopIteration:
            raise RuntimeError("Image placeholder found but no image asset remains.")
        else:
            if event_callback is not None:
                event_callback(
                    "document_processing",
                    "waiting_for_llm",
                    f"Waiting for LLM response for page {page_no} / figure {image_path.name}",
                    page_no,
                    None,
                )
            description = run_with_retries(
                lambda: client.describe_image(image_path),
                on_retry=lambda attempt, exc: event_callback(
                    "document_processing",
                    "retry",
                    f"Retrying LLM call for page {page_no}, attempt {attempt}: {type(exc).__name__}: {exc}",
                    page_no,
                    None,
                )
                if event_callback is not None
                else None,
            ).strip()
            output_parts.append(
                build_visual_markdown_block("Figure", image_path, description)
            )
        cursor = position + len(IMAGE_PLACEHOLDER)

    return "".join(output_parts)


def replace_formula_blocks(
    markdown: str,
    formula_paths: Iterator[Path],
    client: EnrichmentClient,
    page_no: int | None = None,
    event_callback=None,
) -> str:
    def replace_match(match: re.Match[str]) -> str:
        formula_markdown = match.group(0)
        try:
            formula_path = next(formula_paths)
        except StopIteration:
            raise RuntimeError("Formula block found but no formula image asset remains.")
        if event_callback is not None:
            event_callback(
                "document_processing",
                "waiting_for_llm",
                f"Waiting for LLM response for page {page_no} / formula {formula_path.name}",
                page_no,
                None,
            )
        description = run_with_retries(
            lambda: client.describe_formula(formula_path, formula_markdown),
            on_retry=lambda attempt, exc: event_callback(
                "document_processing",
                "retry",
                f"Retrying LLM call for page {page_no}, attempt {attempt}: {type(exc).__name__}: {exc}",
                page_no,
                None,
            )
            if event_callback is not None
            else None,
        ).strip()
        return build_visual_markdown_block("Formula", formula_path, description)

    return FORMULA_BLOCK_PATTERN.sub(replace_match, markdown)


def enrich_page_markdown(
    markdown: str,
    page_no: int,
    table_fragments: Dict[Tuple[int, int], TableFragment],
    image_paths: Iterator[Path],
    formula_paths: Iterator[Path],
    client: EnrichmentClient,
    previous_by_table_id: Dict[str, TableFragment],
    event_callback=None,
) -> str:
    enriched = replace_tables(
        markdown=markdown,
        page_no=page_no,
        table_fragments=table_fragments,
        client=client,
        previous_by_table_id=previous_by_table_id,
        event_callback=event_callback,
    )

    enriched = replace_image_placeholders(
        enriched,
        image_paths,
        client,
        page_no=page_no,
        event_callback=event_callback,
    )

    enriched = replace_formula_blocks(
        enriched,
        formula_paths,
        client,
        page_no=page_no,
        event_callback=event_callback,
    )

    return enriched.strip() + "\n"


def _advance_resume_context_for_page(
    page_no: int,
    markdown: str,
    table_fragments: Dict[Tuple[int, int], TableFragment],
    image_paths: Iterator[Path],
    formula_paths: Iterator[Path],
    previous_by_table_id: Dict[str, TableFragment],
) -> None:
    lines = markdown.splitlines()
    for table_index, _range in enumerate(find_table_line_ranges(lines), start=1):
        fragment = table_fragments.get((page_no, table_index))
        if fragment and fragment.is_multi_page:
            previous_by_table_id[fragment.table_id] = fragment
    for _ in range(markdown.count(IMAGE_PLACEHOLDER)):
        next(image_paths)
    for _match in FORMULA_BLOCK_PATTERN.finditer(markdown):
        next(formula_paths)


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
    table_paths = sorted_asset_paths(docling_assets_dir / TABLE_IMAGE_FOLDER, "table")
    picture_paths = sorted_asset_paths(docling_assets_dir / PICTURE_IMAGE_FOLDER, "picture")
    formula_paths = sorted_asset_paths(docling_assets_dir / FORMULA_IMAGE_FOLDER, "formula")

    require_asset_count(
        kind="Picture",
        expected=count_picture_placeholders(pages),
        actual=len(picture_paths),
        folder=docling_assets_dir / PICTURE_IMAGE_FOLDER,
    )
    require_asset_count(
        kind="Formula",
        expected=count_formula_blocks(pages),
        actual=len(formula_paths),
        folder=docling_assets_dir / FORMULA_IMAGE_FOLDER,
    )
    table_fragments = build_table_fragment_index(
        docling_assets_dir=docling_assets_dir,
        pages=pages,
        table_images=table_paths,
    )

    if enriched_root.exists() and not resume:
        shutil.rmtree(enriched_root)
    enriched_pages_dir.mkdir(parents=True, exist_ok=True)
    copy_visual_asset_folders(docling_assets_dir, enriched_root)

    image_paths = iter(picture_paths)
    formula_path_iter = iter(formula_paths)
    previous_by_table_id: Dict[str, TableFragment] = {}
    stitched_parts: List[str] = []

    print("Document enrichment started.")
    for page_no, markdown in pages.items():
        print(f"  - enriching page {page_no}")
        page_file = enriched_pages_dir / f"page_{page_no:04d}.md"
        if resume and page_file.exists():
            _advance_resume_context_for_page(
                page_no,
                markdown,
                table_fragments,
                image_paths,
                formula_path_iter,
                previous_by_table_id,
            )
            stitched_parts.append(page_file.read_text(encoding="utf-8"))
            continue
        enriched_page = enrich_page_markdown(
            markdown=markdown,
            page_no=page_no,
            table_fragments=table_fragments,
            image_paths=image_paths,
            formula_paths=formula_path_iter,
            client=client,
            previous_by_table_id=previous_by_table_id,
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
