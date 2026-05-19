"""Schemas for vectorless topic retrieval."""

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


class TopicRoute(StrictModel):
    topic: str = Field(min_length=1)
    pages: list[int]
    reason: str = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]


class RoutingDecision(StrictModel):
    routes: list[TopicRoute]
    selected_pages: list[int]
    overall_reason: str = Field(min_length=1)


class PageContext(StrictModel):
    page: int
    path: Path
    markdown: str


class PageEvidence(StrictModel):
    page: int
    useful: bool
    evidence: str
    key_terms: list[str]


class FinalAnswer(StrictModel):
    answer: str
    pages_used: list[int]
    missing_information: list[str] = Field(default_factory=list)


class RetrievalTrace(StrictModel):
    matched_topics: list[str]
    pages_read: list[int]
    files_read: list[str]
    memory_mode: Literal["direct", "compressed"]
    selection_reason: str


class RetrievalOutput(StrictModel):
    final_answer: FinalAnswer
    retrieval_trace: RetrievalTrace
