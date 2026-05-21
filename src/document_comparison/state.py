"""LangGraph state for document comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from .llm import ComparisonClient
from .schemas import (
    ComparisonPlan,
    ComparisonPlanItem,
    ComparisonRunConfig,
    ComparisonStateFile,
    DocumentManifest,
    GapFinding,
    GapReport,
    PageComparisonResult,
    PageContext,
    RegulatoryEvidenceSummary,
    TopicEntry,
)


class DocumentComparisonState(TypedDict, total=False):
    comparison_run_id: str
    comparison_run_dir: Path
    regulatory_root: Path
    sop_root: Path
    start_page: int
    end_page: int | None
    resume: bool
    max_direct_regulatory_pages: int
    max_direct_estimated_tokens: int

    run_config: ComparisonRunConfig
    state_file: ComparisonStateFile
    run_status: Literal["in_progress", "completed", "failed"]

    regulatory_manifest: DocumentManifest
    sop_manifest: DocumentManifest
    regulatory_topic_index: list[TopicEntry]

    current_sop_page: int
    sop_target_page: PageContext
    sop_next_page: PageContext | None
    previous_sop_page_summary: str

    comparison_plan: ComparisonPlan
    pending_plan_items: list[ComparisonPlanItem] | None
    current_plan_item: ComparisonPlanItem | None
    current_item_number: int

    regulatory_page_contexts: list[PageContext]
    estimated_context_tokens: int
    comparison_memory_mode: Literal["direct", "compressed"]
    compressed_regulatory_evidence: list[RegulatoryEvidenceSummary]

    current_gap_finding: GapFinding
    current_page_findings: list[GapFinding]
    current_page_item_result_paths: list[Path]
    completed_item_result_paths: list[Path]
    completed_page_result_paths: list[Path]
    page_result: PageComparisonResult
    final_report: GapReport

    client: ComparisonClient
