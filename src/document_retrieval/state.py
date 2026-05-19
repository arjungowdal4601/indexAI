"""LangGraph state for vectorless document retrieval."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from .llm import RetrievalClient
from .schemas import (
    FinalAnswer,
    PageContext,
    PageEvidence,
    RetrievalTrace,
    RoutingDecision,
    TopicEntry,
)


class DocumentRetrievalState(TypedDict, total=False):
    user_query: str
    topic_index_path: Path
    pages_folder_path: Path
    max_direct_pages: int
    max_direct_estimated_tokens: int
    client: RetrievalClient

    topic_index: list[TopicEntry]
    routing_decision: RoutingDecision
    selected_pages: list[int]
    page_contexts: list[PageContext]
    estimated_context_tokens: int
    memory_mode: Literal["direct", "compressed"]
    compressed_evidence: list[PageEvidence]
    final_answer: FinalAnswer
    retrieval_trace: RetrievalTrace
