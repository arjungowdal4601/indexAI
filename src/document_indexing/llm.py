"""LangChain-backed LLM client for topic indexing."""

from __future__ import annotations

import json
import os
from typing import Protocol

from doc_processing.enrichment import DEFAULT_ENRICHMENT_MODEL
from .prompts import (
    DESCRIPTION_UPDATE_PROMPT,
    TOPIC_EXTRACTION_PROMPT,
    TOPIC_MATCHING_PROMPT,
)
from .schemas import (
    PageMarkdown,
    TopicCandidate,
    TopicCandidateList,
    TopicDescriptionUpdate,
    TopicEntry,
    TopicMatchDecision,
    TopicMatchDecisionList,
)

class TopicIndexingClient(Protocol):
    def extract_candidates(
        self,
        main_pages: list[PageMarkdown],
        context_pages: list[PageMarkdown],
        existing_topics: list[TopicEntry],
    ) -> list[TopicCandidate]:
        ...

    def match_topics(
        self,
        candidates: list[TopicCandidate],
        current_index: list[TopicEntry],
    ) -> list[TopicMatchDecision]:
        ...

    def merge_topic(self, existing_topic: TopicEntry, candidate: TopicCandidate) -> str:
        ...


def format_pages(pages: list[PageMarkdown]) -> str:
    if not pages:
        return "None."
    return "\n\n".join(
        f"PAGE {page.page}\n{page.markdown.strip()}" for page in pages
    )


def summarize_topics(topics: list[TopicEntry]) -> str:
    if not topics:
        return "No existing topics."
    summary = []
    for topic in topics:
        summary.append(
            {
                "topic": topic.topic,
                "pages": topic.pages,
                "description": topic.description,
                "keywords": topic.keywords,
            }
        )
    return json.dumps(summary, ensure_ascii=False, indent=2)


class LangChainTopicIndexingClient:
    def __init__(self, model: str | None = None):
        try:
            from dotenv import load_dotenv
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Document indexing requires python-dotenv and langchain-openai. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for document indexing. "
                "Set OPENAI_API_KEY and rerun python main.py."
            )

        reasoning_effort = "high"

        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model
            or os.getenv("DOC_INDEXING_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_ENRICHMENT_MODEL,
            reasoning_effort=reasoning_effort,
        )
        self.candidate_chain = (
            TOPIC_EXTRACTION_PROMPT
            | self.llm.with_structured_output(TopicCandidateList)
        )
        self.match_chain = (
            TOPIC_MATCHING_PROMPT
            | self.llm.with_structured_output(TopicMatchDecisionList)
        )
        self.description_chain = (
            DESCRIPTION_UPDATE_PROMPT
            | self.llm.with_structured_output(TopicDescriptionUpdate)
        )

    def extract_candidates(
        self,
        main_pages: list[PageMarkdown],
        context_pages: list[PageMarkdown],
        existing_topics: list[TopicEntry],
    ) -> list[TopicCandidate]:
        response = self.candidate_chain.invoke(
            {
                "existing_topic_summary": summarize_topics(existing_topics),
                "main_pages": format_pages(main_pages),
                "context_pages": format_pages(context_pages),
            }
        )
        return list(response.candidates)

    def match_topics(
        self,
        candidates: list[TopicCandidate],
        current_index: list[TopicEntry],
    ) -> list[TopicMatchDecision]:
        response = self.match_chain.invoke(
            {
                "current_index": summarize_topics(current_index),
                "candidates": json.dumps(
                    [candidate.model_dump(mode="json") for candidate in candidates],
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        )
        return list(response.decisions)

    def merge_topic(self, existing_topic: TopicEntry, candidate: TopicCandidate) -> str:
        response = self.description_chain.invoke(
            {
                "existing_topic": json.dumps(
                    existing_topic.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                ),
                "candidate_topic": json.dumps(
                    candidate.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        )
        return response.description.strip()
