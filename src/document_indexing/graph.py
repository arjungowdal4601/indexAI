"""LangGraph wiring and visualization for document indexing."""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from .llm import LangChainTopicIndexingClient, TopicIndexingClient
from .nodes import (
    extract_candidates_node,
    load_state_node,
    match_candidates_node,
    read_index_node,
    read_manifest_node,
    read_window_node,
    update_index_node,
    write_outputs_node,
)
from .routers import route_after_state, route_after_window, route_after_write
from .schemas import IndexingOutput
from .state import DocumentIndexingState
from .storage import (
    PROCESSING_STATE_FILE,
    REVISION_LOG_FILE,
    TOPIC_INDEX_FILE,
    VALIDATION_REPORT_FILE,
)

DEFAULT_MAIN_WINDOW_SIZE = 3
DEFAULT_CONTEXT_WINDOW_SIZE = 2
DEFAULT_TOPIC_INDEX_TOKEN_LIMIT = 80000


def build_document_indexing_graph():
    graph = StateGraph(DocumentIndexingState)

    graph.add_node("load_state", load_state_node)
    graph.add_node("read_manifest", read_manifest_node)
    graph.add_node("read_window", read_window_node)
    graph.add_node("read_index", read_index_node)
    graph.add_node("extract_candidates", extract_candidates_node)
    graph.add_node("match_candidates", match_candidates_node)
    graph.add_node("update_index", update_index_node)
    graph.add_node("write_outputs", write_outputs_node)

    graph.set_entry_point("load_state")
    graph.add_conditional_edges(
        "load_state",
        route_after_state,
        {"read_manifest": "read_manifest", "end": END},
    )
    graph.add_edge("read_manifest", "read_window")
    graph.add_conditional_edges(
        "read_window",
        route_after_window,
        {"read_index": "read_index", "end": END},
    )
    graph.add_edge("read_index", "extract_candidates")
    graph.add_edge("extract_candidates", "match_candidates")
    graph.add_edge("match_candidates", "update_index")
    graph.add_edge("update_index", "write_outputs")
    graph.add_conditional_edges(
        "write_outputs",
        route_after_write,
        {"read_window": "read_window", "end": END},
    )

    return graph.compile()


def export_graph_mermaid(output_path: str | Path = "document_indexing_graph.mmd") -> None:
    graph = build_document_indexing_graph()
    mermaid = graph.get_graph().draw_mermaid()
    Path(output_path).write_text(mermaid, encoding="utf-8")


def run_document_indexing(
    pages_folder_path: str | Path,
    output_folder_path: str | Path,
    document_id: str,
    main_window_size: int = DEFAULT_MAIN_WINDOW_SIZE,
    context_window_size: int = DEFAULT_CONTEXT_WINDOW_SIZE,
    client: TopicIndexingClient | None = None,
    token_limit: int = DEFAULT_TOPIC_INDEX_TOKEN_LIMIT,
) -> IndexingOutput:
    output_folder = Path(output_folder_path)
    output_folder.mkdir(parents=True, exist_ok=True)
    indexing_client = client or LangChainTopicIndexingClient()

    graph = build_document_indexing_graph()
    graph.invoke(
        {
            "document_id": document_id,
            "pages_folder_path": Path(pages_folder_path),
            "output_folder_path": output_folder,
            "main_window_size": int(main_window_size),
            "context_window_size": int(context_window_size),
            "token_limit": int(token_limit),
            "client": indexing_client,
            "step_number": 0,
        }
    )

    return IndexingOutput(
        topic_index_path=output_folder / TOPIC_INDEX_FILE,
        processing_state_path=output_folder / PROCESSING_STATE_FILE,
        revision_log_path=output_folder / REVISION_LOG_FILE,
        validation_report_path=output_folder / VALIDATION_REPORT_FILE,
    )
