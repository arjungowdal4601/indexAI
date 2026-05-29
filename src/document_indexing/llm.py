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
    TopicAsset,
    TopicCandidateDraft,
    TopicCandidateList,
    TopicDescriptionUpdate,
    TopicEntry,
    TopicMatchDecision,
    TopicMatchDecisionList,
)

class TopicIndexingClient(Protocol):
    def extract_candidates(
        self,
        target_page: PageMarkdown,
        target_page_assets: list[TopicAsset],
        previous_page_topics: list[TopicEntry],
        next_page: PageMarkdown | None,
    ) -> list[TopicCandidateDraft]:
        ...

    def match_topics(
        self,
        candidates: list[TopicCandidate],
        current_index: list[TopicEntry],
    ) -> list[TopicMatchDecision]:
        ...

    def merge_topic(self, existing_topic: TopicEntry, candidate: TopicCandidate) -> str:
        ...


def build_extraction_payload(
    *,
    target_page: PageMarkdown,
    target_page_assets: list[TopicAsset],
    previous_page_topics: list[TopicEntry],
    next_page: PageMarkdown | None,
) -> str:
    payload = {
        "previous_page_topics": [
            {
                "topic": topic.topic,
                "description": topic.description,
            }
            for topic in previous_page_topics
        ],
        "target_page_markdown": target_page.markdown.strip(),
        "target_page_assets": [
            asset.model_dump(mode="json") for asset in target_page_assets
        ],
        "next_page_markdown": next_page.markdown.strip()
        if next_page is not None
        else None,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_matching_payload(
    *,
    candidates: list[TopicCandidate],
    existing_topics: list[TopicEntry],
) -> str:
    payload = {
        "candidates": [
            {
                "slot": slot,
                "topic": candidate.topic,
                "description": candidate.description,
            }
            for slot, candidate in enumerate(candidates)
        ],
        "existing_topics": [
            {
                "slot": slot,
                "topic": topic.topic,
                "description": topic.description,
            }
            for slot, topic in enumerate(existing_topics)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


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

        reasoning_effort = "medium"

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
        target_page: PageMarkdown,
        target_page_assets: list[TopicAsset],
        previous_page_topics: list[TopicEntry],
        next_page: PageMarkdown | None,
    ) -> list[TopicCandidateDraft]:
        response = self.candidate_chain.invoke(
            {
                "payload": build_extraction_payload(
                    target_page=target_page,
                    target_page_assets=target_page_assets,
                    previous_page_topics=previous_page_topics,
                    next_page=next_page,
                ),
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
                "payload": build_matching_payload(
                    candidates=candidates,
                    existing_topics=current_index,
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
                "new_candidate": json.dumps(
                    candidate.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        )
        return response.description.strip()
