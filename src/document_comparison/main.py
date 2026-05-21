"""Command line runner for document comparison."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in (None, ""):
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from document_comparison.config import (
    DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    DEFAULT_MAX_DIRECT_REGULATORY_PAGES,
)
from document_comparison.graph import run_document_comparison
from document_comparison.schemas import ComparisonRunOutput


def run_comparison_pipeline(
    regulatory_root: str | Path,
    sop_root: str | Path,
    comparison_run_dir: str | Path | None = None,
    comparison_run_id: str | None = None,
    model: str | None = None,
    start_page: int = 1,
    end_page: int | None = None,
    resume: bool = True,
    max_direct_regulatory_pages: int = DEFAULT_MAX_DIRECT_REGULATORY_PAGES,
    max_direct_estimated_tokens: int = DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
) -> ComparisonRunOutput:
    return run_document_comparison(
        regulatory_root=regulatory_root,
        sop_root=sop_root,
        comparison_run_dir=comparison_run_dir,
        comparison_run_id=comparison_run_id,
        model=model,
        start_page=start_page,
        end_page=end_page,
        resume=resume,
        max_direct_regulatory_pages=max_direct_regulatory_pages,
        max_direct_estimated_tokens=max_direct_estimated_tokens,
    )


def format_comparison_output(output: ComparisonRunOutput) -> str:
    return (
        "## Document Comparison Run\n\n"
        f"Run id: {output.comparison_run_id}\n\n"
        f"Run directory: {output.comparison_run_dir}\n\n"
        f"Gap report JSON: {output.gap_report_path}\n\n"
        f"Gap report Markdown: {output.markdown_report_path}\n\n"
        f"Executive summary: {output.executive_summary_path}\n\n"
        f"Page results written: {len(output.page_result_paths)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare an SOP document root against a regulatory document root."
    )
    parser.add_argument("--regulatory-root", required=True)
    parser.add_argument("--sop-root", required=True)
    parser.add_argument("--comparison-run-dir", default=None)
    parser.add_argument("--comparison-run-id", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--max-direct-regulatory-pages",
        type=int,
        default=DEFAULT_MAX_DIRECT_REGULATORY_PAGES,
    )
    parser.add_argument(
        "--max-direct-estimated-tokens",
        type=int,
        default=DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = run_comparison_pipeline(
        regulatory_root=args.regulatory_root,
        sop_root=args.sop_root,
        comparison_run_dir=args.comparison_run_dir,
        comparison_run_id=args.comparison_run_id,
        model=args.model,
        start_page=args.start_page,
        end_page=args.end_page,
        resume=not args.no_resume,
        max_direct_regulatory_pages=args.max_direct_regulatory_pages,
        max_direct_estimated_tokens=args.max_direct_estimated_tokens,
    )
    print(format_comparison_output(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
