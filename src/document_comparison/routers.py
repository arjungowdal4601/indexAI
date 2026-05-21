"""Conditional edge routers for document comparison."""

from __future__ import annotations

from .state import DocumentComparisonState


def route_after_plan_item_queue(state: DocumentComparisonState) -> str:
    return "next_item" if state.get("current_plan_item") is not None else "page_complete"


def route_after_context_estimate(state: DocumentComparisonState) -> str:
    return state["comparison_memory_mode"]


def route_after_page_result(state: DocumentComparisonState) -> str:
    return "finished" if state.get("run_status") == "completed" else "next_page"
