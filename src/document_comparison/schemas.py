"""Pydantic schemas for SOP-vs-regulatory document comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

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


class DocumentManifest(StrictModel):
    document_id: str = Field(min_length=1)
    role: Literal["regulatory", "sop"]
    root_path: Path
    source_file: Path
    enriched_pages_folder: Path
    page_images_folder: Path
    total_pages: int = Field(ge=1)
    topic_index_path: Path | None = None


class PageContext(StrictModel):
    page: int
    path: Path
    markdown: str


class RegulatoryTopicMapping(StrictModel):
    regulatory_topic: str = Field(min_length=1)
    regulatory_pages: list[int]
    reason: str = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]


class ComparisonPlanItem(StrictModel):
    sop_topic: str = Field(min_length=1)
    sop_page: int
    sop_claim_or_requirement: str = Field(min_length=1)
    sop_evidence_excerpt: str = Field(min_length=1)
    regulatory_mappings: list[RegulatoryTopicMapping]
    comparison_focus: str = Field(min_length=1)


class ComparisonPlan(StrictModel):
    sop_page: int
    plan_items: list[ComparisonPlanItem]
    page_summary: str = Field(min_length=1)
    planning_notes_for_trace: str = Field(min_length=1)


class RegulatoryEvidenceSummary(StrictModel):
    regulatory_page: int
    regulatory_topic: str = Field(min_length=1)
    useful: bool
    evidence: str
    obligations: list[str] = Field(default_factory=list)
    source_excerpt: str = ""


class GapFinding(StrictModel):
    sop_page: int
    sop_topic: str = Field(min_length=1)
    regulatory_topics: list[str]
    regulatory_pages_used: list[int]
    status: Literal[
        "compliant",
        "partially_compliant",
        "missing",
        "conflicting",
        "not_applicable",
        "needs_human_review",
    ]
    severity: Literal["critical", "major", "minor", "informational"]
    confidence: Literal["high", "medium", "low"]
    sop_evidence: str
    regulatory_evidence: str
    gap_explanation: str
    recommended_action: str
    missing_or_weak_elements: list[str] = Field(default_factory=list)


class PageComparisonResult(StrictModel):
    sop_page: int
    sop_page_summary: str
    findings: list[GapFinding]
    page_status: Literal[
        "compliant",
        "partial",
        "major_gaps",
        "needs_human_review",
        "not_applicable",
    ]
    high_priority_count: int = 0
    human_review_count: int = 0


class ReportCounts(StrictModel):
    total_sop_pages_reviewed: int = 0
    total_findings: int = 0
    compliant: int = 0
    partially_compliant: int = 0
    missing: int = 0
    conflicting: int = 0
    not_applicable: int = 0
    needs_human_review: int = 0
    critical: int = 0
    major: int = 0
    minor: int = 0
    informational: int = 0


class GapReport(StrictModel):
    comparison_run_id: str
    regulatory_doc_id: str
    sop_doc_id: str
    counts: ReportCounts
    page_results: list[PageComparisonResult]


class ComparisonRunConfig(StrictModel):
    comparison_run_id: str
    regulatory_doc_id: str | None = None
    sop_doc_id: str | None = None
    regulatory_root: Path
    sop_root: Path
    start_page: int
    end_page: int | None = None
    max_direct_regulatory_pages: int
    max_direct_estimated_tokens: int


class ComparisonStateFile(StrictModel):
    comparison_run_id: str
    last_completed_sop_page: int = 0
    current_sop_page: int = 1
    completed_item_result_paths: list[str] = Field(default_factory=list)
    completed_page_result_paths: list[str] = Field(default_factory=list)
    status: Literal["in_progress", "completed", "failed"] = "in_progress"


class ComparisonRunOutput(StrictModel):
    comparison_run_id: str
    comparison_run_dir: Path
    gap_report_path: Path
    markdown_report_path: Path
    executive_summary_path: Path
    page_result_paths: list[Path]
