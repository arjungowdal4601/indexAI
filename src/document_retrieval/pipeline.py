"""Linear public runner for vectorless document retrieval."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    DEFAULT_MAX_DIRECT_PAGES,
    DEFAULT_PAGES_FOLDER,
    DEFAULT_TOPIC_INDEX_PATH,
)
from .llm import LangChainRetrievalClient, RetrievalClient
from .nodes import (
    answer_from_compressed_evidence_node,
    answer_from_pages_node,
    build_retrieval_trace_node,
    check_page_files_exist_node,
    compress_page_evidence_node,
    estimate_context_size_node,
    load_topic_index_node,
    read_selected_pages_node,
    route_query_to_topics_node,
)
from .schemas import RetrievalOutput


def _debug_steps(state: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "step": "route_query_to_topics",
            "status": "completed",
            "summary": "Mapped the user query to topic-index routes.",
        },
        {
            "step": "read_selected_pages",
            "status": "completed",
            "summary": f"Read {len(state.get('page_contexts', []))} selected page Markdown file(s).",
        },
        {
            "step": "estimate_context_size",
            "status": "completed",
            "summary": f"Selected {state.get('memory_mode')} retrieval memory mode.",
        },
        {
            "step": "answer",
            "status": "completed",
            "summary": "Generated an answer from observable page evidence.",
        },
    ]


def run_document_retrieval(
    user_query: str,
    topic_index_path: str | Path = DEFAULT_TOPIC_INDEX_PATH,
    pages_folder_path: str | Path = DEFAULT_PAGES_FOLDER,
    client: RetrievalClient | None = None,
    model: str | None = None,
    max_direct_pages: int = DEFAULT_MAX_DIRECT_PAGES,
    max_direct_estimated_tokens: int = DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
) -> RetrievalOutput:
    retrieval_client = client or LangChainRetrievalClient(model=model)
    state: dict[str, Any] = {
        "user_query": user_query,
        "topic_index_path": Path(topic_index_path),
        "pages_folder_path": Path(pages_folder_path),
        "client": retrieval_client,
        "max_direct_pages": int(max_direct_pages),
        "max_direct_estimated_tokens": int(max_direct_estimated_tokens),
    }

    state.update(load_topic_index_node(state))
    state.update(route_query_to_topics_node(state))
    check_page_files_exist_node(state)
    state.update(read_selected_pages_node(state))
    state.update(estimate_context_size_node(state))

    if state["memory_mode"] == "direct":
        state.update(answer_from_pages_node(state))
    else:
        state.update(compress_page_evidence_node(state))
        state.update(answer_from_compressed_evidence_node(state))

    state.update(build_retrieval_trace_node(state))
    return RetrievalOutput(
        final_answer=state["final_answer"],
        retrieval_trace=state["retrieval_trace"],
        routing_decision=state.get("routing_decision"),
        selected_pages=list(state.get("selected_pages", [])),
        estimated_context_tokens=state.get("estimated_context_tokens"),
        memory_mode=state.get("memory_mode"),
        compressed_evidence=list(state.get("compressed_evidence", [])),
        debug_steps=_debug_steps(state),
    )
