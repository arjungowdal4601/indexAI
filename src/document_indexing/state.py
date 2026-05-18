"""LangGraph state for the document indexing workflow."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from .llm import TopicIndexingClient
from .schemas import (
    PageManifest,
    PageWindow,
    ProcessingState,
    TopicCandidate,
    TopicEntry,
    TopicMatchDecision,
    ValidationReport,
)


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
