"""Minimal markdown table matching helpers used during enrichment."""

from __future__ import annotations

from typing import List, Tuple

from .config import MIN_TABLE_LINES


def is_probably_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("!["):
        return False
    if stripped.startswith("--- PAGE"):
        return False
    return stripped.count("|") >= 2


def find_table_line_ranges(lines: List[str]) -> List[Tuple[int, int]]:
    """Find consecutive markdown table-like line ranges.

    The returned indexes are used only immediately for in-memory replacement;
    they are not persisted as metadata.
    """
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
            if not line.strip() and index + 1 < len(lines) and is_probably_table_line(lines[index + 1]):
                index += 1
                continue
            break

        if (end - start + 1) >= MIN_TABLE_LINES:
            ranges.append((start, end))

    return ranges
