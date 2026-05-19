"""Standalone command line runner for vectorless document retrieval."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in (None, ""):
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from document_retrieval.config import (
    DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    DEFAULT_MAX_DIRECT_PAGES,
    DEFAULT_PAGES_FOLDER,
    DEFAULT_TOPIC_INDEX_PATH,
)
from document_retrieval.graph import run_document_retrieval
from document_retrieval.schemas import RetrievalOutput


def run_retrieval_pipeline(
    user_query: str,
    topic_index_path: str | Path = DEFAULT_TOPIC_INDEX_PATH,
    pages_folder_path: str | Path = DEFAULT_PAGES_FOLDER,
    model: str | None = None,
    max_direct_pages: int = DEFAULT_MAX_DIRECT_PAGES,
    max_direct_estimated_tokens: int = DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
) -> RetrievalOutput:
    return run_document_retrieval(
        user_query=user_query,
        topic_index_path=Path(topic_index_path),
        pages_folder_path=Path(pages_folder_path),
        model=model,
        max_direct_pages=max_direct_pages,
        max_direct_estimated_tokens=max_direct_estimated_tokens,
    )


def _format_list(items: list[str], empty_text: str = "- None") -> str:
    if not items:
        return empty_text
    return "\n".join(f"- {item}" for item in items)


def format_retrieval_output(output: RetrievalOutput) -> str:
    trace = output.retrieval_trace
    answer = output.final_answer
    pages_used = ", ".join(str(page) for page in answer.pages_used) or "None"
    pages_read = ", ".join(str(page) for page in trace.pages_read) or "None"
    files_read = _format_list(trace.files_read)
    matched_topics = _format_list(trace.matched_topics)
    missing = _format_list(answer.missing_information)

    return (
        "## Retrieval Trace\n\n"
        "Matched topics:\n"
        f"{matched_topics}\n\n"
        f"Pages read: {pages_read}\n\n"
        "Files read:\n"
        f"{files_read}\n\n"
        f"Memory mode: {trace.memory_mode}\n\n"
        "Selection reason:\n"
        f"{trace.selection_reason}\n\n"
        "## Answer\n\n"
        f"{answer.answer}\n\n"
        f"Pages used: {pages_used}\n\n"
        "Missing information:\n"
        f"{missing}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Answer a question from topic_index.json and enriched page Markdown."
    )
    parser.add_argument(
        "query",
        nargs="+",
        help="Question to answer from the indexed document.",
    )
    parser.add_argument(
        "--topic-index",
        default=str(DEFAULT_TOPIC_INDEX_PATH),
        help="Path to topic_index.json.",
    )
    parser.add_argument(
        "--pages-folder",
        default=str(DEFAULT_PAGES_FOLDER),
        help="Folder containing enriched page_*.md files.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the retrieval model. Defaults to DOC_RETRIEVAL_MODEL, OPENAI_MODEL, or gpt-5.4-mini.",
    )
    parser.add_argument(
        "--max-direct-pages",
        type=int,
        default=DEFAULT_MAX_DIRECT_PAGES,
    )
    parser.add_argument(
        "--max-direct-estimated-tokens",
        type=int,
        default=DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = run_retrieval_pipeline(
        user_query=" ".join(args.query),
        topic_index_path=args.topic_index,
        pages_folder_path=args.pages_folder,
        model=args.model,
        max_direct_pages=args.max_direct_pages,
        max_direct_estimated_tokens=args.max_direct_estimated_tokens,
    )
    print(format_retrieval_output(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
