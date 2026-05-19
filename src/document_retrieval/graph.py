"""LangGraph wiring and public runner for vectorless document retrieval."""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

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
from .routers import route_after_context_estimate
from .schemas import RetrievalOutput
from .state import DocumentRetrievalState


def build_document_retrieval_graph():
    builder = StateGraph(DocumentRetrievalState)

    builder.add_node("load_topic_index", load_topic_index_node)
    builder.add_node("route_query_to_topics", route_query_to_topics_node)
    builder.add_node("check_page_files_exist", check_page_files_exist_node)
    builder.add_node("read_selected_pages", read_selected_pages_node)
    builder.add_node("estimate_context_size", estimate_context_size_node)
    builder.add_node("answer_from_pages", answer_from_pages_node)
    builder.add_node("compress_page_evidence", compress_page_evidence_node)
    builder.add_node(
        "answer_from_compressed_evidence",
        answer_from_compressed_evidence_node,
    )
    builder.add_node("build_retrieval_trace", build_retrieval_trace_node)

    builder.add_edge(START, "load_topic_index")
    builder.add_edge("load_topic_index", "route_query_to_topics")
    builder.add_edge("route_query_to_topics", "check_page_files_exist")
    builder.add_edge("check_page_files_exist", "read_selected_pages")
    builder.add_edge("read_selected_pages", "estimate_context_size")
    builder.add_conditional_edges(
        "estimate_context_size",
        route_after_context_estimate,
        {
            "direct": "answer_from_pages",
            "compressed": "compress_page_evidence",
        },
    )
    builder.add_edge("compress_page_evidence", "answer_from_compressed_evidence")
    builder.add_edge("answer_from_pages", "build_retrieval_trace")
    builder.add_edge("answer_from_compressed_evidence", "build_retrieval_trace")
    builder.add_edge("build_retrieval_trace", END)

    return builder.compile()


def export_graph_mermaid(output_path: str | Path = "document_retrieval_graph.mmd") -> None:
    graph = build_document_retrieval_graph()
    mermaid = graph.get_graph().draw_mermaid()
    Path(output_path).write_text(mermaid, encoding="utf-8")


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
    graph = build_document_retrieval_graph()
    result = graph.invoke(
        {
            "user_query": user_query,
            "topic_index_path": Path(topic_index_path),
            "pages_folder_path": Path(pages_folder_path),
            "client": retrieval_client,
            "max_direct_pages": int(max_direct_pages),
            "max_direct_estimated_tokens": int(max_direct_estimated_tokens),
        }
    )
    return RetrievalOutput(
        final_answer=result["final_answer"],
        retrieval_trace=result["retrieval_trace"],
    )
