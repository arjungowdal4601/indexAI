"""Small helper steps for the sequential document indexing pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

from backend.services.retry_utils import run_with_retries

from .config import DEFAULT_TOPIC_MATCH_BATCH_SIZE
from .llm import TopicIndexingClient
from .schemas import (
    PageManifest,
    PageWindow,
    ProcessingState,
    TopicAsset,
    TopicCandidate,
    TopicCandidateDraft,
    TopicEntry,
    TopicMatchDecision,
    ValidationReport,
)
from .storage import (
    append_revision_log,
    build_topic_index_diagnostics,
    clean_topic_index,
    write_processing_state,
    write_topic_index,
    write_validation_report,
)

EventCallback = Callable[[str, str, str, int | None, int | None], None]


def candidate_from_draft(
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


def decision_by_candidate(
    decisions: list[TopicMatchDecision],
) -> dict[int, TopicMatchDecision]:
    return {decision.candidate_batch_slot: decision for decision in decisions}


def merge_assets(existing: list[TopicAsset], new: list[TopicAsset]) -> list[TopicAsset]:
    merged: list[TopicAsset] = []
    seen = set()
    for asset in existing + new:
        key = (asset.page, asset.type, asset.path)
        if key in seen:
            continue
        seen.add(key)
        merged.append(asset)
    return merged


def remove_first_topic(
    topics: list[TopicEntry],
    target: TopicEntry,
) -> list[TopicEntry]:
    remaining: list[TopicEntry] = []
    removed = False
    for topic in topics:
        if not removed and topic is target:
            removed = True
            continue
        remaining.append(topic)
    if removed:
        return remaining

    remaining = []
    for topic in topics:
        if not removed and topic == target:
            removed = True
            continue
        remaining.append(topic)
    return remaining


def merge_candidate_into_topic(
    *,
    existing_topic: TopicEntry,
    candidate: TopicCandidate,
    client: TopicIndexingClient,
    output_dir: str | Path,
    document_id: str,
    processing_state: ProcessingState,
    event_callback: EventCallback | None,
    target_page: int,
    total_pages: int,
) -> TopicEntry:
    merged_description = run_indexing_llm_call(
        output_dir=output_dir,
        document_id=document_id,
        processing_state=processing_state,
        stage="merge_topic",
        message=f"Waiting for LLM response for indexing page {target_page} merge topic",
        target_page=target_page,
        total_pages=total_pages,
        event_callback=event_callback,
        func=lambda: client.merge_topic(existing_topic, candidate),
    )
    return TopicEntry(
        topic=existing_topic.topic,
        pages=sorted(set(existing_topic.pages + candidate.pages)),
        description=merged_description,
        assets=merge_assets(existing_topic.assets, candidate.assets),
    )


def write_failed_indexing_state(
    output_dir: str | Path,
    document_id: str,
    processing_state: ProcessingState,
    stage: str,
    exc: Exception,
    failed_page: int | None = None,
) -> None:
    write_processing_state(
        output_dir,
        ProcessingState(
            document_id=document_id,
            last_completed_page=processing_state.last_completed_page,
            next_start_page=processing_state.next_start_page,
            status="failed",
            failed_page=failed_page,
            failed_stage=stage,
            error_type=type(exc).__name__,
            error_message=str(exc),
        ),
    )


def run_indexing_llm_call(
    *,
    output_dir: str | Path,
    document_id: str,
    processing_state: ProcessingState,
    stage: str,
    message: str,
    target_page: int | None,
    total_pages: int | None,
    event_callback: EventCallback | None,
    func,
):
    if event_callback is not None:
        event_callback(
            "document_indexing",
            "waiting_for_llm",
            message,
            target_page,
            total_pages,
        )
    try:
        return run_with_retries(
            func,
            on_retry=lambda attempt, exc: event_callback(
                "document_indexing",
                "retry",
                f"Retrying indexing LLM call for page {target_page}, attempt {attempt}: {type(exc).__name__}: {exc}",
                target_page,
                total_pages,
            )
            if event_callback is not None
            else None,
        )
    except Exception as exc:
        write_failed_indexing_state(
            output_dir=output_dir,
            document_id=document_id,
            processing_state=processing_state,
            stage=stage,
            exc=exc,
            failed_page=target_page,
        )
        raise


def update_topic_index(
    *,
    current_index: list[TopicEntry],
    candidates: list[TopicCandidate],
    client: TopicIndexingClient,
    output_dir: str | Path,
    document_id: str,
    processing_state: ProcessingState,
    event_callback: EventCallback | None,
    target_page: int,
    total_pages: int,
    topic_match_batch_size: int = DEFAULT_TOPIC_MATCH_BATCH_SIZE,
) -> tuple[list[TopicEntry], list[str], list[str]]:
    topics = list(current_index)
    search_pool = list(current_index)
    unresolved = list(enumerate(candidates))
    added: list[str] = []
    updated: list[str] = []

    batch_size = max(1, int(topic_match_batch_size))
    while unresolved and search_pool:
        batch_start = max(0, len(search_pool) - batch_size)
        batch_topics = search_pool[batch_start:]
        search_pool = search_pool[:batch_start]
        batch_candidates = [candidate for _, candidate in unresolved]
        decisions = run_indexing_llm_call(
            output_dir=output_dir,
            document_id=document_id,
            processing_state=processing_state,
            stage="match_topics",
            message=f"Waiting for LLM response for indexing page {target_page} topic matching",
            target_page=target_page,
            total_pages=total_pages,
            event_callback=event_callback,
            func=lambda: client.match_topics(batch_candidates, batch_topics),
        )
        decisions_by_candidate = decision_by_candidate(decisions)
        next_unresolved: list[tuple[int, TopicCandidate]] = []
        matched_slots: list[int] = []
        candidates_by_matched_slot: dict[int, list[TopicCandidate]] = {}

        for local_slot, (_original_slot, candidate) in enumerate(unresolved):
            decision = decisions_by_candidate.get(local_slot)
            matched_slot = (
                decision.matched_batch_slot
                if decision is not None
                and decision.decision == "update_existing"
                and decision.matched_batch_slot is not None
                and 0 <= decision.matched_batch_slot < len(batch_topics)
                else None
            )
            if matched_slot is None:
                next_unresolved.append((_original_slot, candidate))
                continue

            if matched_slot not in candidates_by_matched_slot:
                matched_slots.append(matched_slot)
                candidates_by_matched_slot[matched_slot] = []
            candidates_by_matched_slot[matched_slot].append(candidate)

        for matched_slot in matched_slots:
            existing_topic = batch_topics[matched_slot]
            replacement = existing_topic
            for candidate in candidates_by_matched_slot[matched_slot]:
                replacement = merge_candidate_into_topic(
                    existing_topic=replacement,
                    candidate=candidate,
                    client=client,
                    output_dir=output_dir,
                    document_id=document_id,
                    processing_state=processing_state,
                    event_callback=event_callback,
                    target_page=target_page,
                    total_pages=total_pages,
                )
            topics = remove_first_topic(topics, existing_topic)
            topics.append(replacement)
            updated.append(existing_topic.topic)

        unresolved = next_unresolved

    for _candidate_slot, candidate in unresolved:
        topics.append(
            TopicEntry(
                topic=candidate.topic,
                pages=sorted(set(candidate.pages)),
                description=candidate.description,
                assets=merge_assets([], candidate.assets),
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

    added_text = (
        "\n".join(
            f"- {topic} (reason: no existing topic matched after backward batch search)"
            for topic in added_topics
        )
        or "- None"
    )
    updated_text = (
        "\n".join(
            f"- {topic} (reason: matched existing topic and merged current page evidence)"
            for topic in updated_topics
        )
        or "- None"
    )
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
        f"Estimated topic index size: {validation_report.estimated_tokens}\n\n"
        "Warnings:\n"
        f"{warnings_text}"
    )


def index_page(
    *,
    output_dir: str | Path,
    document_id: str,
    processing_state: ProcessingState,
    manifest: PageManifest,
    window: PageWindow,
    current_topic_index: list[TopicEntry],
    client: TopicIndexingClient,
    step_number: int,
    event_callback: EventCallback | None,
    topic_match_batch_size: int = DEFAULT_TOPIC_MATCH_BATCH_SIZE,
    write_diagnostics: bool = False,
) -> tuple[ProcessingState, int]:
    target_page = window.target_page.page
    raw_candidates = run_indexing_llm_call(
        output_dir=output_dir,
        document_id=document_id,
        processing_state=processing_state,
        stage="extract_candidates",
        message=f"Waiting for LLM response for indexing page {target_page}",
        target_page=target_page,
        total_pages=manifest.total_pages,
        event_callback=event_callback,
        func=lambda: client.extract_candidates(
            window.target_page,
            window.target_page_assets,
            window.previous_page_topics,
            window.next_page,
        ),
    )
    candidates = [
        candidate_from_draft(
            draft,
            target_page=target_page,
            target_page_assets=window.target_page_assets,
        )
        for draft in raw_candidates
    ]
    updated_index, added, updated = update_topic_index(
        current_index=current_topic_index,
        candidates=candidates,
        client=client,
        output_dir=output_dir,
        document_id=document_id,
        processing_state=processing_state,
        event_callback=event_callback,
        target_page=target_page,
        total_pages=manifest.total_pages,
        topic_match_batch_size=topic_match_batch_size,
    )
    try:
        cleaned_index, cleanup_fixes = clean_topic_index(updated_index)
    except Exception as exc:
        write_failed_indexing_state(
            output_dir=output_dir,
            document_id=document_id,
            processing_state=processing_state,
            stage="clean_topic_index",
            exc=exc,
            failed_page=target_page,
        )
        raise

    report = build_topic_index_diagnostics(cleaned_index, cleanup_fixes)
    next_step_number = step_number + 1

    last_completed_page = target_page
    next_start_page = last_completed_page + 1
    status: Literal["in_progress", "completed"] = (
        "completed" if next_start_page > manifest.total_pages else "in_progress"
    )
    next_state = ProcessingState(
        document_id=document_id,
        last_completed_page=last_completed_page,
        next_start_page=next_start_page,
        status=status,
    )

    write_topic_index(
        output_dir,
        cleaned_index,
        step_number=next_step_number,
        write_backup=write_diagnostics,
    )
    revision_log_entry = build_revision_log_entry(
        step_number=next_step_number,
        window=window,
        added_topics=added,
        updated_topics=updated,
        validation_report=report,
    )
    append_revision_log(output_dir, revision_log_entry)
    if write_diagnostics:
        write_validation_report(output_dir, report)
    write_processing_state(output_dir, next_state)

    if event_callback is not None:
        event_callback(
            "document_indexing",
            "indexing_page",
            f"Indexing page {last_completed_page} of {manifest.total_pages}",
            last_completed_page,
            manifest.total_pages,
        )

    return next_state, next_step_number
