"""Conditional edge routers for the document indexing graph."""

from __future__ import annotations

from .state import DocumentIndexingState


def route_after_state(state: DocumentIndexingState) -> str:
    return "end" if state.get("status") == "completed" else "read_manifest"


def route_after_window(state: DocumentIndexingState) -> str:
    return "end" if state.get("status") == "completed" else "read_index"


def route_after_write(state: DocumentIndexingState) -> str:
    return "end" if state.get("status") == "completed" else "read_window"
