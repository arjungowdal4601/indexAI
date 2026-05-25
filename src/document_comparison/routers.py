"""Conditional edge routers for document comparison."""

from __future__ import annotations

from .state import DocumentComparisonState


def route_after_plan_item_queue(state: DocumentComparisonState) -> str:
    return "next_item" if state.get("current_plan_item") is not None else "page_complete"


def route_after_context_estimate(state: DocumentComparisonState) -> str:
    return state["comparison_memory_mode"]


def route_after_page_result(state: DocumentComparisonState) -> str:
    return "finished" if state.get("run_status") == "completed" else "next_page"


def route_after_regulatory_index(state: DocumentComparisonState) -> str:
    current_page = int(state.get("current_sop_page") or 1)
    end_page = int(state.get("end_page") or current_page)
    return "finished" if current_page > end_page else "read_page"
