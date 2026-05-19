"""Conditional edge routers for vectorless document retrieval."""

from __future__ import annotations

from .state import DocumentRetrievalState


def route_after_context_estimate(state: DocumentRetrievalState) -> str:
    return state["memory_mode"]
