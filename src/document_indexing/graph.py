"""LangGraph orchestration for document indexing."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph

from .llm import LangChainTopicIndexingClient, TopicIndexingClient
from .schemas import (
    IndexingOutput,
    PageManifest,
    PageWindow,
    ProcessingState,
    TopicCandidate,
    TopicEntry,
    TopicMatchDecision,
    ValidationReport,
)
from .storage import (
    PROCESSING_STATE_FILE,
    REVISION_LOG_FILE,
    TOPIC_INDEX_FILE,
    VALIDATION_REPORT_FILE,
    append_revision_log,
    load_processing_state,
    load_topic_index,
    read_page_manifest,
    read_page_window,
    write_processing_state,
    write_topic_index,
    write_validation_report,
)
from .validator import validate_topic_index

DEFAULT_MAIN_WINDOW_SIZE = 3
DEFAULT_CONTEXT_WINDOW_SIZE = 2
DEFAULT_TOPIC_INDEX_TOKEN_LIMIT = 80000


class DocumentIndexingState(TypedDict, total=False):
    document_id: str
    pages_folder_path: Path
    output_folder_path: Path
    main_window_size: int
    context_window_size: int
    token_limit: int
    processing_state: ProcessingState
    manifest: PageManifest
    current_window: PageWindow
    current_topic_index: list[TopicEntry]
    candidate_topics: list[TopicCandidate]
    match_decisions: list[TopicMatchDecision]
    updated_topic_index: list[TopicEntry]
    validation_report: ValidationReport
    revision_log_entry: str
    step_number: int
    status: str
    client: TopicIndexingClient


def _restrict_candidate_to_main_pages(
    candidate: TopicCandidate,
    main_pages: set[int],
) -> Optional[TopicCandidate]:
    pages = sorted({page for page in candidate.pages if page in main_pages})
    if not pages:
        return None
    return TopicCandidate(
        topic=candidate.topic,
        pages=pages,
        description=candidate.description,
        keywords=candidate.keywords,
    )


def _decision_by_candidate(
    decisions: list[TopicMatchDecision],
) -> dict[str, TopicMatchDecision]:
    return {decision.candidate_topic: decision for decision in decisions}


def _find_topic(topics: list[TopicEntry], topic_name: str | None) -> TopicEntry | None:
    if not topic_name:
        return None
    normalized = topic_name.strip().lower()
    for topic in topics:
        if topic.topic.strip().lower() == normalized:
            return topic
    return None


def _merge_keywords(existing: list[str], new: list[str]) -> list[str]:
    merged = []
    seen = set()
    for keyword in existing + new:
        cleaned = " ".join(keyword.strip().split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged


def _update_topic_index(
    current_index: list[TopicEntry],
    candidates: list[TopicCandidate],
    decisions: list[TopicMatchDecision],
    client: TopicIndexingClient,
) -> tuple[list[TopicEntry], list[str], list[str]]:
    topics = list(current_index)
    added: list[str] = []
    updated: list[str] = []
    decisions_by_candidate = _decision_by_candidate(decisions)

    for candidate in candidates:
        decision = decisions_by_candidate.get(candidate.topic)
        if decision is None:
            decision = TopicMatchDecision(
                candidate_topic=candidate.topic,
                decision="add_new",
                matched_topic=None,
                reason="No matcher decision returned.",
            )

        existing_topic = _find_topic(topics, decision.matched_topic)
        if decision.decision == "update_existing" and existing_topic is not None:
            merged_description = client.merge_topic(existing_topic, candidate)
            replacement = TopicEntry(
                topic=existing_topic.topic,
                pages=sorted(set(existing_topic.pages + candidate.pages)),
                description=merged_description,
                keywords=_merge_keywords(existing_topic.keywords, candidate.keywords),
            )
            topics = [
                replacement if topic.topic == existing_topic.topic else topic
                for topic in topics
            ]
            updated.append(existing_topic.topic)
            continue

        topics.append(
            TopicEntry(
                topic=candidate.topic,
                pages=sorted(set(candidate.pages)),
                description=candidate.description,
                keywords=_merge_keywords([], candidate.keywords),
            )
        )
        added.append(candidate.topic)

    return topics, added, updated


def build_revision_log_entry(
    step_number: int,
    window: PageWindow,
    added_topics: list[str],
    updated_topics: list[str],
    validation_report: ValidationReport,
) -> str:
    main_pages = [page.page for page in window.main_pages]
    context_pages = [page.page for page in window.context_pages]
    main_range = f"{main_pages[0]}-{main_pages[-1]}" if main_pages else "none"
    context_range = (
        f"{context_pages[0]}-{context_pages[-1]}" if context_pages else "none"
    )

    added_text = "\n".join(f"- {topic}" for topic in added_topics) or "- None"
    updated_text = "\n".join(f"- {topic}" for topic in updated_topics) or "- None"
    warnings_text = (
        "\n".join(f"- {warning}" for warning in validation_report.warnings)
        if validation_report.warnings
        else "- None"
    )

    return (
        f"## Step {step_number:03d}\n\n"
        f"Main pages: {main_range}\n"
        f"Context pages: {context_range}\n\n"
        "Added topics:\n"
        f"{added_text}\n\n"
        "Updated topics:\n"
        f"{updated_text}\n\n"
        f"Validation: {validation_report.status}\n"
        f"Estimated tokens: {validation_report.estimated_tokens}\n\n"
        "Warnings:\n"
        f"{warnings_text}"
    )


def build_document_indexing_graph():
    graph = StateGraph(DocumentIndexingState)

    def load_state_node(state: DocumentIndexingState) -> DocumentIndexingState:
        processing_state = load_processing_state(
            output_dir=state["output_folder_path"],
            document_id=state["document_id"],
            main_window_size=state["main_window_size"],
            context_window_size=state["context_window_size"],
        )
        return {"processing_state": processing_state, "status": processing_state.status}

    def read_manifest_node(state: DocumentIndexingState) -> DocumentIndexingState:
        manifest = read_page_manifest(state["pages_folder_path"])
        if manifest.missing_pages:
            raise FileNotFoundError(
                f"Missing page markdown files: {manifest.missing_pages}"
            )
        return {"manifest": manifest}

    def read_window_node(state: DocumentIndexingState) -> DocumentIndexingState:
        processing_state = state["processing_state"]
        manifest = state["manifest"]
        if processing_state.status == "completed":
            return {}
        if processing_state.next_start_page > manifest.total_pages:
            return {"status": "completed"}
        window = read_page_window(
            manifest=manifest,
            start_page=processing_state.next_start_page,
            main_window_size=state["main_window_size"],
            context_window_size=state["context_window_size"],
        )
        return {"current_window": window}

    def read_index_node(state: DocumentIndexingState) -> DocumentIndexingState:
        index_path = Path(state["output_folder_path"]) / TOPIC_INDEX_FILE
        return {"current_topic_index": load_topic_index(index_path)}

    def extract_candidates_node(state: DocumentIndexingState) -> DocumentIndexingState:
        window = state["current_window"]
        main_pages = {page.page for page in window.main_pages}
        raw_candidates = state["client"].extract_candidates(
            window.main_pages,
            window.context_pages,
            state["current_topic_index"],
        )
        candidates = []
        for candidate in raw_candidates:
            restricted = _restrict_candidate_to_main_pages(candidate, main_pages)
            if restricted is not None:
                candidates.append(restricted)
        return {"candidate_topics": candidates}

    def match_candidates_node(state: DocumentIndexingState) -> DocumentIndexingState:
        decisions = state["client"].match_topics(
            state["candidate_topics"],
            state["current_topic_index"],
        )
        return {"match_decisions": decisions}

    def update_index_node(state: DocumentIndexingState) -> DocumentIndexingState:
        updated_index, added, updated = _update_topic_index(
            current_index=state["current_topic_index"],
            candidates=state["candidate_topics"],
            decisions=state["match_decisions"],
            client=state["client"],
        )
        report, cleaned_index = validate_topic_index(
            updated_index,
            token_limit=state["token_limit"],
        )
        step_number = int(state.get("step_number", 0)) + 1
        revision_log_entry = build_revision_log_entry(
            step_number=step_number,
            window=state["current_window"],
            added_topics=added,
            updated_topics=updated,
            validation_report=report,
        )
        return {
            "updated_topic_index": cleaned_index,
            "validation_report": report,
            "revision_log_entry": revision_log_entry,
            "step_number": step_number,
        }

    def write_outputs_node(state: DocumentIndexingState) -> DocumentIndexingState:
        if state["validation_report"].status != "passed":
            failed_state = ProcessingState(
                document_id=state["document_id"],
                last_completed_page=state["processing_state"].last_completed_page,
                next_start_page=state["processing_state"].next_start_page,
                main_window_size=state["main_window_size"],
                context_window_size=state["context_window_size"],
                status="failed",
            )
            write_processing_state(state["output_folder_path"], failed_state)
            write_validation_report(state["output_folder_path"], state["validation_report"])
            raise RuntimeError(
                f"Index validation failed: {state['validation_report'].warnings}"
            )

        window = state["current_window"]
        last_completed_page = window.main_pages[-1].page
        next_start_page = last_completed_page + 1
        manifest = state["manifest"]
        status: Literal["in_progress", "completed"] = (
            "completed" if next_start_page > manifest.total_pages else "in_progress"
        )
        next_state = ProcessingState(
            document_id=state["document_id"],
            last_completed_page=last_completed_page,
            next_start_page=next_start_page,
            main_window_size=state["main_window_size"],
            context_window_size=state["context_window_size"],
            status=status,
        )

        write_topic_index(
            state["output_folder_path"],
            state["updated_topic_index"],
            step_number=state["step_number"],
        )
        write_validation_report(state["output_folder_path"], state["validation_report"])
        write_processing_state(state["output_folder_path"], next_state)
        append_revision_log(state["output_folder_path"], state["revision_log_entry"])

        return {"processing_state": next_state, "status": status}

    def route_after_state(state: DocumentIndexingState) -> str:
        return "end" if state.get("status") == "completed" else "read_manifest"

    def route_after_window(state: DocumentIndexingState) -> str:
        return "end" if state.get("status") == "completed" else "read_index"

    def route_after_write(state: DocumentIndexingState) -> str:
        return "end" if state.get("status") == "completed" else "read_window"

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
