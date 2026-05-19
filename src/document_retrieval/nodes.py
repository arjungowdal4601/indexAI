"""LangGraph node functions for vectorless document retrieval."""

from __future__ import annotations

import json

from .config import (
    DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    DEFAULT_MAX_DIRECT_PAGES,
    estimate_tokens,
)
from .schemas import PageContext, PageEvidence
from .state import DocumentRetrievalState
from .storage import (
    load_topic_index,
    missing_page_markdowns,
    normalize_page_numbers,
    read_selected_page_markdowns,
)


def _format_page_context(page_contexts: list[PageContext]) -> str:
    return "\n\n".join(
        f"PAGE {context.page}\n{context.markdown.strip()}"
        for context in page_contexts
    )


def _format_page_evidence(evidence: list[PageEvidence]) -> str:
    payload = [item.model_dump(mode="json") for item in evidence]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_preliminary_trace(state: DocumentRetrievalState) -> str:
    decision = state["routing_decision"]
    routes = [
        {
            "topic": route.topic,
            "pages": route.pages,
            "reason": route.reason,
            "confidence": route.confidence,
        }
        for route in decision.routes
    ]
    payload = {
        "matched_topics": routes,
        "selected_pages": state["selected_pages"],
        "memory_mode": state["memory_mode"],
        "selection_reason": decision.overall_reason,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def load_topic_index_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    topic_index = load_topic_index(state["topic_index_path"])
    return {"topic_index": topic_index}


def route_query_to_topics_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    topic_index_json = json.dumps(
        [topic.model_dump(mode="json") for topic in state["topic_index"]],
        ensure_ascii=False,
        indent=2,
    )
    decision = state["client"].route_query_to_topics(
        user_query=state["user_query"],
        topic_index_json=topic_index_json,
    )
    return {
        "routing_decision": decision,
        "selected_pages": normalize_page_numbers(decision.selected_pages),
    }


def check_page_files_exist_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    missing = missing_page_markdowns(
        pages_folder_path=state["pages_folder_path"],
        selected_pages=state["selected_pages"],
    )
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Selected page files not found: {missing_text}")
    return {}


def read_selected_pages_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    page_contexts = read_selected_page_markdowns(
        pages_folder_path=state["pages_folder_path"],
        selected_pages=state["selected_pages"],
    )
    return {"page_contexts": page_contexts}


def estimate_context_size_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    estimated_tokens = sum(
        estimate_tokens(page.markdown) for page in state["page_contexts"]
    )
    max_direct_pages = int(state.get("max_direct_pages", DEFAULT_MAX_DIRECT_PAGES))
    max_direct_estimated_tokens = int(
        state.get(
            "max_direct_estimated_tokens",
            DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
        )
    )
    memory_mode = (
        "direct"
        if len(state["page_contexts"]) <= max_direct_pages
        and estimated_tokens <= max_direct_estimated_tokens
        else "compressed"
    )
    return {
        "estimated_context_tokens": estimated_tokens,
        "memory_mode": memory_mode,
    }


def answer_from_pages_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    answer = state["client"].answer_from_pages(
        user_query=state["user_query"],
        page_context=_format_page_context(state["page_contexts"]),
        retrieval_trace=_format_preliminary_trace(state),
    )
    return {"final_answer": answer}


def compress_page_evidence_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    compressed_evidence = [
        state["client"].compress_page_evidence(
            user_query=state["user_query"],
            page_context=page_context,
        )
        for page_context in state["page_contexts"]
    ]
    return {"compressed_evidence": compressed_evidence}


def answer_from_compressed_evidence_node(
    state: DocumentRetrievalState,
) -> DocumentRetrievalState:
    answer = state["client"].answer_from_compressed_evidence(
        user_query=state["user_query"],
        compressed_evidence=_format_page_evidence(state["compressed_evidence"]),
        retrieval_trace=_format_preliminary_trace(state),
    )
    return {"final_answer": answer}


def build_retrieval_trace_node(state: DocumentRetrievalState) -> DocumentRetrievalState:
    decision = state["routing_decision"]
    trace = {
        "matched_topics": [route.topic for route in decision.routes],
        "pages_read": [context.page for context in state["page_contexts"]],
        "files_read": [context.path.name for context in state["page_contexts"]],
        "memory_mode": state["memory_mode"],
        "selection_reason": decision.overall_reason,
    }
    return {"retrieval_trace": trace}
