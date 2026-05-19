"""LangGraph node functions for document indexing."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from .llm import TopicIndexingClient
from .schemas import (
    PageWindow,
    ProcessingState,
    TopicAsset,
    TopicCandidate,
    TopicCandidateDraft,
    TopicEntry,
    TopicMatchDecision,
    ValidationReport,
)
from .state import DocumentIndexingState
from .storage import (
    TOPIC_INDEX_FILE,
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


def _candidate_from_draft(
    draft: TopicCandidateDraft,
    target_page: int,
    target_page_assets: list[TopicAsset],
) -> TopicCandidate:
    assets_by_path = {asset.path: asset for asset in target_page_assets}
    selected_assets = []
    seen_paths = set()
    for path in draft.asset_paths:
        asset = assets_by_path.get(path)
        if asset is None or asset.path in seen_paths:
            continue
        seen_paths.add(asset.path)
        selected_assets.append(asset)
    return TopicCandidate(
        topic=draft.topic,
        pages=[target_page],
        description=draft.description,
        assets=selected_assets,
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


def _merge_assets(existing: list[TopicAsset], new: list[TopicAsset]) -> list[TopicAsset]:
    merged: list[TopicAsset] = []
    seen = set()
    for asset in existing + new:
        key = (asset.page, asset.type, asset.path)
        if key in seen:
            continue
        seen.add(key)
        merged.append(asset)
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
                assets=_merge_assets(existing_topic.assets, candidate.assets),
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
                assets=_merge_assets([], candidate.assets),
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
    previous_topics = (
        ", ".join(topic.topic for topic in window.previous_page_topics) or "None"
    )
    next_page = str(window.next_page.page) if window.next_page is not None else "None"

    added_text = "\n".join(f"- {topic}" for topic in added_topics) or "- None"
    updated_text = "\n".join(f"- {topic}" for topic in updated_topics) or "- None"
    warnings_text = (
        "\n".join(f"- {warning}" for warning in validation_report.warnings)
        if validation_report.warnings
        else "- None"
    )

    return (
        f"## Step {step_number:03d}\n\n"
        f"Target page: {window.target_page.page}\n"
        f"Previous page indexed topics: {previous_topics}\n"
        f"Next context page: {next_page}\n\n"
        "Added topics:\n"
        f"{added_text}\n\n"
        "Updated topics:\n"
        f"{updated_text}\n\n"
        f"Validation: {validation_report.status}\n"
        f"Estimated tokens: {validation_report.estimated_tokens}\n\n"
        "Warnings:\n"
        f"{warnings_text}"
    )


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
        raise FileNotFoundError(f"Missing page markdown files: {manifest.missing_pages}")
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
        target_page=processing_state.next_start_page,
        current_topic_index=state.get("current_topic_index", []),
        include_next_page=state.get("context_window_size", 1) > 0,
    )
    return {"current_window": window}


def read_index_node(state: DocumentIndexingState) -> DocumentIndexingState:
    index_path = Path(state["output_folder_path"]) / TOPIC_INDEX_FILE
    return {"current_topic_index": load_topic_index(index_path)}


def extract_candidates_node(state: DocumentIndexingState) -> DocumentIndexingState:
    window = state["current_window"]
    target_page = window.target_page.page
    raw_candidates = state["client"].extract_candidates(
        window.target_page,
        window.target_page_assets,
        window.previous_page_topics,
        window.next_page,
        state["current_topic_index"],
    )
    candidates = [
        _candidate_from_draft(
            draft,
            target_page=target_page,
            target_page_assets=window.target_page_assets,
        )
        for draft in raw_candidates
    ]
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
        raise RuntimeError(f"Index validation failed: {state['validation_report'].warnings}")

    window = state["current_window"]
    last_completed_page = window.target_page.page
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
