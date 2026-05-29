"""Markdown enrichment rendering and visual-asset replacement helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterator, List

from .config import IMAGE_PLACEHOLDER
from .asset_registry import page_assets_by_kind
from .enrichment_client import EnrichmentClient, TableDescriptionRequest
from .retries import run_with_retries
from .table_utils import find_table_line_ranges

FORMULA_BLOCK_PATTERN = re.compile(
    r"(?s)"
    r"(\$\$.*?\$\$"
    r"|\\\[.*?\\\]"
    r"|\\begin\{equation\*?\}.*?\\end\{equation\*?\}"
    r"|\\begin\{align\*?\}.*?\\end\{align\*?\}"
    r"|\\begin\{gather\*?\}.*?\\end\{gather\*?\}"
    r"|\\begin\{multline\*?\}.*?\\end\{multline\*?\})"
)


def build_visual_markdown_block(label: str, image_path: Path, description: str) -> str:
    description = description.strip()
    relative_path = f"{image_path.parent.name}/{image_path.name}".replace("\\", "/")
    asset_id = image_path.stem
    inner_block = f"![{label}]({relative_path})\n\n{description}".strip()
    return f"[ASSET {asset_id} START]\n\n{inner_block}\n\n[ASSET {asset_id} END]"


def _asset_image_path(docling_assets_dir: Path, asset: dict) -> Path:
    return docling_assets_dir / asset["path"]


def _table_id(asset: dict) -> str:
    return f"table_{int(asset.get('global_index') or asset['local_index']):03d}"


def _emit_waiting(event_callback, message: str, page_no: int | None) -> None:
    if event_callback is not None:
        event_callback(
            "document_processing",
            "waiting_for_llm",
            message,
            page_no,
            None,
        )


def count_picture_placeholders(pages: Dict[int, str]) -> int:
    return sum(markdown.count(IMAGE_PLACEHOLDER) for markdown in pages.values())


def count_formula_blocks(pages: Dict[int, str]) -> int:
    return sum(1 for markdown in pages.values() for _ in FORMULA_BLOCK_PATTERN.finditer(markdown))


def _emit_retry(event_callback, page_no: int | None, attempt: int, exc: Exception) -> None:
    if event_callback is not None:
        event_callback(
            "document_processing",
            "retry",
            f"Retrying LLM call for page {page_no}, attempt {attempt}: {type(exc).__name__}: {exc}",
            page_no,
            None,
        )


def _describe_table_asset(
    asset: dict,
    *,
    page_no: int,
    current_markdown: str,
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
    fail_fast: bool = True,
) -> str:
    request = TableDescriptionRequest(
        table_id=_table_id(asset),
        page_no=page_no,
        current_markdown=current_markdown,
        current_image_path=_asset_image_path(docling_assets_dir, asset),
    )

    def describe() -> str:
        return client.describe_table(request)

    try:
        return run_with_retries(
            describe,
            on_retry=lambda attempt, exc: _emit_retry(event_callback, page_no, attempt, exc),
        ).strip()
    except Exception as exc:
        if fail_fast:
            raise
        return f"description unavailable: {type(exc).__name__}: {exc}"


def _describe_picture_asset(
    asset: dict,
    *,
    page_no: int,
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
    fail_fast: bool = True,
) -> str:
    image_path = _asset_image_path(docling_assets_dir, asset)
    try:
        return run_with_retries(
            lambda: client.describe_image(image_path),
            on_retry=lambda attempt, exc: _emit_retry(event_callback, page_no, attempt, exc),
        ).strip()
    except Exception as exc:
        if fail_fast:
            raise
        return f"description unavailable: {type(exc).__name__}: {exc}"


def _describe_formula_asset(
    asset: dict,
    *,
    page_no: int,
    formula_markdown: str,
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
    fail_fast: bool = True,
) -> str:
    image_path = _asset_image_path(docling_assets_dir, asset)
    try:
        return run_with_retries(
            lambda: client.describe_formula(image_path, formula_markdown),
            on_retry=lambda attempt, exc: _emit_retry(event_callback, page_no, attempt, exc),
        ).strip()
    except Exception as exc:
        if fail_fast:
            raise
        return f"description unavailable: {type(exc).__name__}: {exc}"


def replace_tables_with_page_assets(
    markdown: str,
    *,
    page_no: int,
    table_assets: list[dict],
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
) -> tuple[str, list[dict]]:
    lines = markdown.splitlines()
    ranges = find_table_line_ranges(lines)
    if not ranges:
        return markdown, [
            {"asset": asset, "reason": "unmatched_table_block"}
            for asset in table_assets
        ]

    output_lines: List[str] = []
    cursor = 0
    placed_count = 0

    for table_index, (start, end) in enumerate(ranges, start=1):
        output_lines.extend(lines[cursor:start])
        if placed_count >= len(table_assets):
            output_lines.extend(lines[start : end + 1])
            cursor = end + 1
            continue

        asset = table_assets[placed_count]
        current_markdown = "\n".join(lines[start : end + 1])
        _emit_waiting(
            event_callback,
            f"Waiting for LLM response for page {page_no} / table {table_index}",
            page_no,
        )
        description = _describe_table_asset(
            asset,
            page_no=page_no,
            current_markdown=current_markdown,
            client=client,
            docling_assets_dir=docling_assets_dir,
            event_callback=event_callback,
        )
        output_lines.append(
            build_visual_markdown_block(
                "Table",
                _asset_image_path(docling_assets_dir, asset),
                description,
            )
        )
        placed_count += 1
        cursor = end + 1

    output_lines.extend(lines[cursor:])
    unresolved = [
        {"asset": asset, "reason": "unmatched_table_block"}
        for asset in table_assets[placed_count:]
    ]
    return "\n".join(output_lines), unresolved


def replace_pictures_with_page_assets(
    markdown: str,
    *,
    page_no: int,
    picture_assets: list[dict],
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
) -> tuple[str, list[dict]]:
    output_parts: List[str] = []
    cursor = 0
    placed_count = 0

    while True:
        position = markdown.find(IMAGE_PLACEHOLDER, cursor)
        if position == -1:
            output_parts.append(markdown[cursor:])
            break

        output_parts.append(markdown[cursor:position])
        if placed_count >= len(picture_assets):
            output_parts.append(IMAGE_PLACEHOLDER)
            cursor = position + len(IMAGE_PLACEHOLDER)
            continue

        asset = picture_assets[placed_count]
        image_path = _asset_image_path(docling_assets_dir, asset)
        _emit_waiting(
            event_callback,
            f"Waiting for LLM response for page {page_no} / figure {image_path.name}",
            page_no,
        )
        description = _describe_picture_asset(
            asset,
            page_no=page_no,
            client=client,
            docling_assets_dir=docling_assets_dir,
            event_callback=event_callback,
        )
        output_parts.append(build_visual_markdown_block("Figure", image_path, description))
        placed_count += 1
        cursor = position + len(IMAGE_PLACEHOLDER)

    unresolved = [
        {"asset": asset, "reason": "unmatched_picture_placeholder"}
        for asset in picture_assets[placed_count:]
    ]
    return "".join(output_parts), unresolved


def replace_formulas_with_page_assets(
    markdown: str,
    *,
    page_no: int,
    formula_assets: list[dict],
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
) -> tuple[str, list[dict]]:
    placed_count = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal placed_count
        formula_markdown = match.group(0)
        if placed_count >= len(formula_assets):
            return formula_markdown

        asset = formula_assets[placed_count]
        image_path = _asset_image_path(docling_assets_dir, asset)
        _emit_waiting(
            event_callback,
            f"Waiting for LLM response for page {page_no} / formula {image_path.name}",
            page_no,
        )
        description = _describe_formula_asset(
            asset,
            page_no=page_no,
            formula_markdown=formula_markdown,
            client=client,
            docling_assets_dir=docling_assets_dir,
            event_callback=event_callback,
        )
        placed_count += 1
        return build_visual_markdown_block("Formula", image_path, description)

    rendered = FORMULA_BLOCK_PATTERN.sub(replace_match, markdown)
    unresolved = [
        {"asset": asset, "reason": "unmatched_formula_block"}
        for asset in formula_assets[placed_count:]
    ]
    return rendered, unresolved


def _unresolved_heading(kind: str, index: int) -> str:
    label = {"picture": "Figure", "table": "Table", "formula": "Formula"}[kind]
    return f"### {label} (Unresolved #{index})"


def _unresolved_description(
    unresolved: dict,
    *,
    page_no: int,
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
) -> str:
    asset = unresolved["asset"]
    kind = asset["kind"]
    if kind == "table":
        return _describe_table_asset(
            asset,
            page_no=page_no,
            current_markdown="",
            client=client,
            docling_assets_dir=docling_assets_dir,
            event_callback=event_callback,
            fail_fast=False,
        )
    if kind == "formula":
        return _describe_formula_asset(
            asset,
            page_no=page_no,
            formula_markdown="",
            client=client,
            docling_assets_dir=docling_assets_dir,
            event_callback=event_callback,
            fail_fast=False,
        )
    return _describe_picture_asset(
        asset,
        page_no=page_no,
        client=client,
        docling_assets_dir=docling_assets_dir,
        event_callback=event_callback,
        fail_fast=False,
    )


def render_unresolved_assets_section(
    *,
    page_no: int,
    unresolved_assets: list[dict],
    client: EnrichmentClient,
    docling_assets_dir: Path,
    event_callback=None,
) -> str:
    if not unresolved_assets:
        return ""

    parts = [
        "> Status: PARTIAL_AUTOMATION_VERIFY_REQUIRED",
        "> Some page-local assets could not be placed exactly; preserved below.",
        "",
        f"## Unresolved Assets (Page {page_no})",
    ]
    counts = {"picture": 0, "table": 0, "formula": 0}

    for unresolved in unresolved_assets:
        asset = unresolved["asset"]
        kind = asset["kind"]
        counts[kind] += 1
        label = {"picture": "Figure", "table": "Table", "formula": "Formula"}[kind]
        description = _unresolved_description(
            unresolved,
            page_no=page_no,
            client=client,
            docling_assets_dir=docling_assets_dir,
            event_callback=event_callback,
        )
        parts.extend(
            [
                "",
                _unresolved_heading(kind, counts[kind]),
                build_visual_markdown_block(
                    label,
                    _asset_image_path(docling_assets_dir, asset),
                    description,
                ),
                f"- source_page: {asset['source_page']}",
                f"- local_index: {asset['local_index']}",
                f"- reason: {unresolved['reason']}",
            ]
        )

    return "\n".join(parts).strip()


def enrich_page_markdown_from_registry(
    *,
    markdown: str,
    page_no: int,
    page_entry: dict,
    docling_assets_dir: Path,
    client: EnrichmentClient,
    event_callback=None,
) -> str:
    grouped_assets = page_assets_by_kind(page_entry)
    enriched, unresolved_tables = replace_tables_with_page_assets(
        markdown,
        page_no=page_no,
        table_assets=grouped_assets["table"],
        client=client,
        docling_assets_dir=docling_assets_dir,
        event_callback=event_callback,
    )
    enriched, unresolved_pictures = replace_pictures_with_page_assets(
        enriched,
        page_no=page_no,
        picture_assets=grouped_assets["picture"],
        client=client,
        docling_assets_dir=docling_assets_dir,
        event_callback=event_callback,
    )
    enriched, unresolved_formulas = replace_formulas_with_page_assets(
        enriched,
        page_no=page_no,
        formula_assets=grouped_assets["formula"],
        client=client,
        docling_assets_dir=docling_assets_dir,
        event_callback=event_callback,
    )
    unresolved_section = render_unresolved_assets_section(
        page_no=page_no,
        unresolved_assets=unresolved_tables + unresolved_pictures + unresolved_formulas,
        client=client,
        docling_assets_dir=docling_assets_dir,
        event_callback=event_callback,
    )
    if unresolved_section:
        enriched = enriched.rstrip() + "\n\n" + unresolved_section
    return enriched.strip() + "\n"


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
                on_retry=lambda attempt, exc: _emit_retry(event_callback, page_no, attempt, exc),
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
            on_retry=lambda attempt, exc: _emit_retry(event_callback, page_no, attempt, exc),
        ).strip()
        return build_visual_markdown_block("Formula", formula_path, description)

    return FORMULA_BLOCK_PATTERN.sub(replace_match, markdown)
