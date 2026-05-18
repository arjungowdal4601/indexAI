"""
Stage 1B: Deterministic table-continuity detection.

This module reads Docling page-wise markdown files and detects only multi-page
continued tables using markdown table structure.

No LLM is used here.
No OpenAI call is used here.
No table-name/id matching is used here.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    BOTTOM_LINE_RATIO,
    CONTINUITY_THRESHOLD,
    MIN_TABLE_COLUMNS,
    MIN_TABLE_LINES,
    ONLY_WRITE_MULTI_PAGE_TABLES,
    TOP_LINE_RATIO,
)


@dataclass
class TableBlock:
    block_id: str
    page_no: int
    block_index_on_page: int
    start_line: int
    end_line: int
    line_count: int
    page_total_lines: int
    raw_markdown: str
    column_count: int
    row_count: int
    has_separator: bool
    has_header: bool
    header_cells: List[str]
    first_data_row_cells: List[str]
    last_data_row_cells: List[str]
    starts_near_top: bool
    ends_near_bottom: bool
    text_before_table: str
    text_after_table: str


@dataclass
class LogicalTableInternal:
    table_id: str
    start_page: int
    end_page: int
    pages: List[int]
    is_multi_page: bool
    fragment_count: int
    fragments: List[Dict[str, Any]]
    confidence: float


# -----------------------------------------------------------------------------
# Markdown table helpers
# -----------------------------------------------------------------------------

def is_probably_table_line(line: str) -> bool:
    """Detect markdown table-like lines from pipe structure only."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("!["):
        return False
    if stripped.startswith("--- PAGE"):
        return False
    if stripped.count("|") < 2:
        return False
    return True


def split_markdown_row(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def is_separator_row(line: str) -> bool:
    cells = split_markdown_row(line)
    if not cells:
        return False

    for cell in cells:
        compact = cell.strip()
        if not compact:
            return False
        if not re.fullmatch(r":?-{2,}:?", compact):
            return False

    return True


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def token_set(text: str) -> set:
    return set(re.findall(r"[a-zA-Z0-9_]+", normalize_text(text)))


def jaccard_similarity(a: str, b: str) -> float:
    sa = token_set(a)
    sb = token_set(b)

    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0

    return len(sa & sb) / len(sa | sb)


def row_shape_signature(cells: List[str]) -> Dict[str, Any]:
    return {
        "cell_count": len(cells),
        "non_empty_cells": sum(1 for cell in cells if cell.strip()),
        "avg_cell_len": round(sum(len(cell) for cell in cells) / max(len(cells), 1), 2),
    }


# -----------------------------------------------------------------------------
# Page loading and table block extraction
# -----------------------------------------------------------------------------

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


def find_table_line_ranges(lines: List[str]) -> List[Tuple[int, int]]:
    """Find consecutive markdown table-like line ranges."""
    ranges: List[Tuple[int, int]] = []
    index = 0

    while index < len(lines):
        if not is_probably_table_line(lines[index]):
            index += 1
            continue

        start = index
        end = index
        index += 1

        while index < len(lines):
            line = lines[index]

            if is_probably_table_line(line):
                end = index
                index += 1
                continue

            # Allow one blank line inside a table if the next line is still table-like.
            if not line.strip() and index + 1 < len(lines) and is_probably_table_line(lines[index + 1]):
                index += 1
                continue

            break

        if (end - start + 1) >= MIN_TABLE_LINES:
            ranges.append((start, end))

    return ranges


def most_common_int(values: List[int]) -> int:
    counter = Counter(values)
    return counter.most_common(1)[0][0]


def extract_table_block(
    page_no: int,
    block_index_on_page: int,
    start: int,
    end: int,
    lines: List[str],
) -> Optional[TableBlock]:
    table_lines = [line for line in lines[start : end + 1] if is_probably_table_line(line)]
    if len(table_lines) < MIN_TABLE_LINES:
        return None

    parsed_rows = [split_markdown_row(line) for line in table_lines]
    column_counts = [len(row) for row in parsed_rows if len(row) >= MIN_TABLE_COLUMNS]
    if not column_counts:
        return None

    column_count = most_common_int(column_counts)
    if column_count < MIN_TABLE_COLUMNS:
        return None

    has_separator = any(is_separator_row(line) for line in table_lines)
    has_header = False
    header_cells: List[str] = []
    data_rows: List[List[str]] = []

    # Standard markdown table: header row followed by separator row.
    if len(table_lines) >= 2 and is_separator_row(table_lines[1]):
        has_header = True
        header_cells = split_markdown_row(table_lines[0])
        data_rows = [split_markdown_row(line) for line in table_lines[2:] if not is_separator_row(line)]
    else:
        # Continuation table fragments may not repeat the header/separator.
        data_rows = [split_markdown_row(line) for line in table_lines if not is_separator_row(line)]

    first_data_row_cells = data_rows[0] if data_rows else []
    last_data_row_cells = data_rows[-1] if data_rows else []

    page_total_lines = max(len(lines), 1)
    starts_near_top = (start / page_total_lines) <= TOP_LINE_RATIO
    ends_near_bottom = (end / page_total_lines) >= BOTTOM_LINE_RATIO

    text_before = "\n".join(lines[:start]).strip()
    text_after = "\n".join(lines[end + 1 :]).strip()

    block_id = f"p{page_no:04d}_t{block_index_on_page:02d}"

    return TableBlock(
        block_id=block_id,
        page_no=page_no,
        block_index_on_page=block_index_on_page,
        start_line=start + 1,
        end_line=end + 1,
        line_count=end - start + 1,
        page_total_lines=page_total_lines,
        raw_markdown="\n".join(table_lines),
        column_count=column_count,
        row_count=len(data_rows),
        has_separator=has_separator,
        has_header=has_header,
        header_cells=header_cells,
        first_data_row_cells=first_data_row_cells,
        last_data_row_cells=last_data_row_cells,
        starts_near_top=starts_near_top,
        ends_near_bottom=ends_near_bottom,
        text_before_table=text_before,
        text_after_table=text_after,
    )


def extract_all_table_blocks(pages: Dict[int, str]) -> List[TableBlock]:
    all_blocks: List[TableBlock] = []

    for page_no, markdown in pages.items():
        lines = markdown.splitlines()
        ranges = find_table_line_ranges(lines)

        block_counter = 0
        for start, end in ranges:
            block_counter += 1
            block = extract_table_block(
                page_no=page_no,
                block_index_on_page=block_counter,
                start=start,
                end=end,
                lines=lines,
            )
            if block:
                all_blocks.append(block)

    return all_blocks


# -----------------------------------------------------------------------------
# Cross-page continuity detection
# -----------------------------------------------------------------------------

def has_strong_heading_before_table(text: str) -> bool:
    if not text.strip():
        return False

    last_lines = [line.strip() for line in text.splitlines() if line.strip()][-6:]
    for line in last_lines:
        if line.startswith("--- PAGE"):
            continue
        if line.startswith("#"):
            return True
        if re.match(r"^(table|figure|section|appendix)\b", line, flags=re.IGNORECASE):
            return True
        if re.match(r"^\d+(\.\d+)*\s+[A-Z]", line):
            return True
    return False


def has_strong_heading_after_previous_table(text: str) -> bool:
    if not text.strip():
        return False

    first_lines = [line.strip() for line in text.splitlines() if line.strip()][:6]
    for line in first_lines:
        if line.startswith("--- PAGE"):
            continue
        if line.startswith("#"):
            return True
        if re.match(r"^(table|figure|section|appendix)\b", line, flags=re.IGNORECASE):
            return True
        if re.match(r"^\d+(\.\d+)*\s+[A-Z]", line):
            return True
    return False


def compare_blocks_for_continuity(prev: TableBlock, curr: TableBlock) -> Tuple[bool, float]:
    """Return whether curr continues prev, plus continuity score."""
    score = 0.0

    # Only consecutive pages are considered continuation candidates.
    if curr.page_no != prev.page_no + 1:
        return False, 0.0

    # Strongest signal: column compatibility.
    if curr.column_count == prev.column_count:
        score += 2.0
    elif abs(curr.column_count - prev.column_count) == 1:
        score += 0.75
    else:
        return False, score

    # Boundary behavior.
    if prev.ends_near_bottom:
        score += 1.25
    if curr.starts_near_top:
        score += 1.25

    # Header behavior: continuation fragments often omit header or repeat it.
    prev_header_text = " | ".join(prev.header_cells)
    curr_header_text = " | ".join(curr.header_cells)

    if not curr.has_header:
        score += 1.5
    else:
        header_sim = jaccard_similarity(prev_header_text, curr_header_text)
        if header_sim >= 0.60:
            score += 1.5

    # Little text around the page boundary suggests overflow.
    trailing_text_len = len(normalize_text(prev.text_after_table))
    leading_text_len = len(normalize_text(curr.text_before_table))

    if trailing_text_len <= 120:
        score += 0.75
    if leading_text_len <= 160:
        score += 0.75

    # Strong new headings reduce confidence because they likely indicate a new table.
    if has_strong_heading_before_table(curr.text_before_table):
        score -= 2.0
    if has_strong_heading_after_previous_table(prev.text_after_table):
        score -= 1.0

    # Row shape compatibility.
    prev_last_shape = row_shape_signature(prev.last_data_row_cells)
    curr_first_shape = row_shape_signature(curr.first_data_row_cells)
    if prev_last_shape["cell_count"] == curr_first_shape["cell_count"] == prev.column_count:
        score += 0.5

    return score >= CONTINUITY_THRESHOLD, round(score, 2)


def group_logical_tables(blocks: List[TableBlock]) -> List[LogicalTableInternal]:
    """Merge page-level table blocks into logical tables."""
    if not blocks:
        return []

    sorted_blocks = sorted(blocks, key=lambda block: (block.page_no, block.block_index_on_page))

    groups: List[List[TableBlock]] = []
    group_scores: List[List[float]] = []

    current_group: List[TableBlock] = [sorted_blocks[0]]
    current_scores: List[float] = []

    for curr in sorted_blocks[1:]:
        prev = current_group[-1]
        is_continuation, score = compare_blocks_for_continuity(prev, curr)

        if is_continuation:
            current_group.append(curr)
            current_scores.append(score)
        else:
            groups.append(current_group)
            group_scores.append(current_scores)
            current_group = [curr]
            current_scores = []

    groups.append(current_group)
    group_scores.append(current_scores)

    logical_tables: List[LogicalTableInternal] = []

    for idx, group in enumerate(groups, start=1):
        pages = sorted(set(block.page_no for block in group))
        scores = group_scores[idx - 1]
        confidence = round(sum(scores) / max(len(scores), 1), 2) if len(group) > 1 else 1.0

        fragments = [
            {
                "page": block.page_no,
                "table_index_on_page": block.block_index_on_page,
                "block_id": block.block_id,
            }
            for block in group
        ]

        logical_tables.append(
            LogicalTableInternal(
                table_id=f"table_{idx:03d}",
                start_page=min(pages),
                end_page=max(pages),
                pages=pages,
                is_multi_page=len(pages) > 1,
                fragment_count=len(group),
                fragments=fragments,
                confidence=confidence,
            )
        )

    return logical_tables


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def build_minimal_output_payload(
    logical_tables: List[LogicalTableInternal],
) -> Dict[str, Any]:
    """Create the production JSON payload: small and easy to read."""
    if ONLY_WRITE_MULTI_PAGE_TABLES:
        selected_tables = [table for table in logical_tables if table.is_multi_page]
    else:
        selected_tables = logical_tables

    multi_page_tables = [table for table in logical_tables if table.is_multi_page]

    return {
        "multi_page_table_count": len(multi_page_tables),
        "tables": [
            {
                "table_id": table.table_id,
                "is_multi_page": table.is_multi_page,
                "start_page": table.start_page,
                "end_page": table.end_page,
                "pages": table.pages,
                "confidence": table.confidence,
            }
            for table in selected_tables
        ],
    }


def detect_table_continuity(
    page_md_dir: str | Path,
    output_json_path: str | Path,
) -> Dict[str, Any]:
    """Detect multi-page table continuity and write a minimal JSON file."""
    page_md_dir = Path(page_md_dir)
    output_json_path = Path(output_json_path)

    pages = read_page_markdowns(page_md_dir)
    blocks = extract_all_table_blocks(pages)
    logical_tables = group_logical_tables(blocks)

    payload = build_minimal_output_payload(logical_tables)

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Table continuity detection complete.")
    print(f"Detected table blocks: {len(blocks)}")
    print(f"Multi-page tables: {payload['multi_page_table_count']}")
    print(f"Table continuity JSON: {output_json_path}")

    return payload
