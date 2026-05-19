"""Schemas for the document indexing workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopicAsset(StrictModel):
    page: int
    type: Literal["figure", "table", "formula"]
    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TopicEntry(StrictModel):
    topic: str = Field(min_length=1)
    pages: list[int]
    description: str = Field(min_length=1)
    assets: list[TopicAsset] = Field(default_factory=list)


class TopicCandidate(StrictModel):
    topic: str = Field(min_length=1)
    pages: list[int]
    description: str = Field(min_length=1)
    assets: list[TopicAsset] = Field(default_factory=list)


class TopicCandidateDraft(StrictModel):
    topic: str = Field(min_length=1)
    description: str = Field(min_length=1)
    asset_paths: list[str] = Field(default_factory=list)


class TopicCandidateList(StrictModel):
    candidates: list[TopicCandidateDraft]


class TopicMatchDecision(StrictModel):
    candidate_topic: str = Field(min_length=1)
    decision: Literal["add_new", "update_existing"]
    matched_topic: Optional[str] = None
    reason: str = ""


class TopicMatchDecisionList(StrictModel):
    decisions: list[TopicMatchDecision]


class TopicDescriptionUpdate(StrictModel):
    description: str = Field(min_length=1)


class PageManifestEntry(StrictModel):
    page: int
    path: Path


class PageManifest(StrictModel):
    total_pages: int
    pages: list[PageManifestEntry]
    missing_pages: list[int] = Field(default_factory=list)


class PageMarkdown(StrictModel):
    page: int
    markdown: str


class PageWindow(StrictModel):
    previous_page_topics: list[TopicEntry]
    target_page: PageMarkdown
    target_page_assets: list[TopicAsset] = Field(default_factory=list)
    next_page: PageMarkdown | None = None


class ProcessingState(StrictModel):
    document_id: str
    last_completed_page: int = 0
    next_start_page: int = 1
    main_window_size: int
    context_window_size: int
    status: Literal["in_progress", "completed", "failed"] = "in_progress"


class ValidationReport(StrictModel):
    status: Literal["passed", "failed"]
    warnings: list[str] = Field(default_factory=list)
    fixes_applied: list[str] = Field(default_factory=list)
    estimated_tokens: int = 0


class IndexingOutput(StrictModel):
    topic_index_path: Path
    processing_state_path: Path
    revision_log_path: Path
    validation_report_path: Path
