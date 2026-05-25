"""LangChain-backed client for document comparison."""

from __future__ import annotations

import os
from typing import Protocol

from backend.services.retry_utils import is_transient_error, run_with_retries

from .config import (
    DEFAULT_COMPARISON_MODEL,
    DEFAULT_EXECUTOR_REASONING_EFFORT,
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_RETRY_INITIAL_DELAY_SECONDS,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    DEFAULT_PLANNER_REASONING_EFFORT,
)
from .prompts import (
    COMPARISON_PLAN_PROMPT,
    COMPRESS_REGULATORY_EVIDENCE_PROMPT,
    GAP_ANALYSIS_PROMPT,
)
from .schemas import (
    ComparisonPlan,
    ComparisonPlanItem,
    GapFinding,
    PageContext,
    RegulatoryEvidenceSummary,
)


def _is_transient_llm_error(exc: Exception) -> bool:
    return is_transient_error(exc)


def _invoke_with_retry(
    chain,
    payload: dict,
    operation: str,
    max_attempts: int = DEFAULT_LLM_MAX_RETRIES,
    initial_delay_seconds: float = DEFAULT_LLM_RETRY_INITIAL_DELAY_SECONDS,
):
    return run_with_retries(
        lambda: chain.invoke(payload),
        max_attempts=max_attempts,
        initial_delay_seconds=initial_delay_seconds,
        on_retry=lambda attempt, exc: print(
            f"Transient LLM error during {operation}; "
            f"retrying attempt {attempt + 1}/{max_attempts}: {type(exc).__name__}: {exc}",
            flush=True,
        ),
    )


class ComparisonClient(Protocol):
    def plan_sop_page_comparison(
        self,
        sop_target_page: PageContext,
        sop_next_page: PageContext | None,
        previous_sop_page_summary: str,
        regulatory_topic_index_json: str,
    ) -> ComparisonPlan:
        ...

    def compress_regulatory_evidence(
        self,
        plan_item: ComparisonPlanItem,
        regulatory_page_context: PageContext,
    ) -> RegulatoryEvidenceSummary:
        ...

    def execute_gap_analysis(
        self,
        plan_item: ComparisonPlanItem,
        regulatory_evidence: str,
        comparison_memory_mode: str,
    ) -> GapFinding:
        ...


class LangChainComparisonClient:
    def __init__(self, model: str | None = None):
        try:
            from dotenv import load_dotenv
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Document comparison requires python-dotenv and langchain-openai. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for document comparison. "
                "Set OPENAI_API_KEY and rerun the comparison command."
            )

        model_name = (
            model
            or os.getenv("DOC_COMPARISON_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_COMPARISON_MODEL
        )
        planner_llm = ChatOpenAI(
            api_key=api_key,
            model=model_name,
            reasoning_effort=DEFAULT_PLANNER_REASONING_EFFORT,
            timeout=DEFAULT_LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        executor_llm = ChatOpenAI(
            api_key=api_key,
            model=model_name,
            reasoning_effort=DEFAULT_EXECUTOR_REASONING_EFFORT,
            timeout=DEFAULT_LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.plan_chain = (
            COMPARISON_PLAN_PROMPT
            | planner_llm.with_structured_output(ComparisonPlan, method="json_schema")
        )
        self.compression_chain = (
            COMPRESS_REGULATORY_EVIDENCE_PROMPT
            | executor_llm.with_structured_output(RegulatoryEvidenceSummary, method="json_schema")
        )
        self.gap_chain = (
            GAP_ANALYSIS_PROMPT
            | executor_llm.with_structured_output(GapFinding, method="json_schema")
        )

    def plan_sop_page_comparison(
        self,
        sop_target_page: PageContext,
        sop_next_page: PageContext | None,
        previous_sop_page_summary: str,
        regulatory_topic_index_json: str,
    ) -> ComparisonPlan:
        return self.plan_chain.invoke(
            {
                "sop_page_number": sop_target_page.page,
                "sop_page_markdown": sop_target_page.markdown,
                "sop_next_page_markdown": (
                    sop_next_page.markdown if sop_next_page is not None else ""
                ),
                "previous_sop_page_summary": previous_sop_page_summary,
                "regulatory_topic_index_json": regulatory_topic_index_json,
            },
        )

    def compress_regulatory_evidence(
        self,
        plan_item: ComparisonPlanItem,
        regulatory_page_context: PageContext,
    ) -> RegulatoryEvidenceSummary:
        regulatory_topic = (
            plan_item.regulatory_mappings[0].regulatory_topic
            if plan_item.regulatory_mappings
            else "Unmapped regulatory topic"
        )
        return self.compression_chain.invoke(
            {
                "sop_claim": plan_item.sop_claim_or_requirement,
                "comparison_focus": plan_item.comparison_focus,
                "regulatory_topic": regulatory_topic,
                "regulatory_page_number": regulatory_page_context.page,
                "regulatory_page_markdown": regulatory_page_context.markdown,
            },
        )

    def execute_gap_analysis(
        self,
        plan_item: ComparisonPlanItem,
        regulatory_evidence: str,
        comparison_memory_mode: str,
    ) -> GapFinding:
        return self.gap_chain.invoke(
            {
                "sop_page": plan_item.sop_page,
                "sop_topic": plan_item.sop_topic,
                "sop_evidence": plan_item.sop_evidence_excerpt,
                "regulatory_topics": ", ".join(
                    mapping.regulatory_topic for mapping in plan_item.regulatory_mappings
                ),
                "regulatory_evidence": regulatory_evidence,
                "comparison_focus": (
                    f"{plan_item.comparison_focus}\nMemory mode: "
                    f"{comparison_memory_mode}"
                ),
            },
        )
