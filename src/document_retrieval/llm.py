"""LangChain-backed LLM client for vectorless document retrieval."""

from __future__ import annotations

import os
from typing import Protocol

from .config import DEFAULT_RETRIEVAL_MODEL
from .prompts import (
    ANSWER_FROM_COMPRESSED_EVIDENCE_PROMPT,
    ANSWER_FROM_PAGES_PROMPT,
    COMPRESS_PAGE_EVIDENCE_PROMPT,
    ROUTE_QUERY_TO_TOPICS_PROMPT,
)
from .schemas import FinalAnswer, PageContext, PageEvidence, RoutingDecision


class RetrievalClient(Protocol):
    def route_query_to_topics(
        self,
        user_query: str,
        topic_index_json: str,
    ) -> RoutingDecision:
        ...

    def compress_page_evidence(
        self,
        user_query: str,
        page_context: PageContext,
    ) -> PageEvidence:
        ...

    def answer_from_pages(
        self,
        user_query: str,
        page_context: str,
        retrieval_trace: str,
    ) -> FinalAnswer:
        ...

    def answer_from_compressed_evidence(
        self,
        user_query: str,
        compressed_evidence: str,
        retrieval_trace: str,
    ) -> FinalAnswer:
        ...


class LangChainRetrievalClient:
    def __init__(self, model: str | None = None):
        try:
            from dotenv import load_dotenv
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Document retrieval requires python-dotenv and langchain-openai. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for document retrieval. "
                "Set OPENAI_API_KEY and rerun the retrieval command."
            )

        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model
            or os.getenv("DOC_RETRIEVAL_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_RETRIEVAL_MODEL,
            reasoning_effort="medium",
        )
        self.router_chain = (
            ROUTE_QUERY_TO_TOPICS_PROMPT
            | self.llm.with_structured_output(RoutingDecision)
        )
        self.evidence_chain = (
            COMPRESS_PAGE_EVIDENCE_PROMPT
            | self.llm.with_structured_output(PageEvidence)
        )
        self.answer_chain = (
            ANSWER_FROM_PAGES_PROMPT
            | self.llm.with_structured_output(FinalAnswer)
        )
        self.compressed_answer_chain = (
            ANSWER_FROM_COMPRESSED_EVIDENCE_PROMPT
            | self.llm.with_structured_output(FinalAnswer)
        )

    def route_query_to_topics(
        self,
        user_query: str,
        topic_index_json: str,
    ) -> RoutingDecision:
        return self.router_chain.invoke(
            {
                "user_query": user_query,
                "topic_index_json": topic_index_json,
            }
        )

    def compress_page_evidence(
        self,
        user_query: str,
        page_context: PageContext,
    ) -> PageEvidence:
        return self.evidence_chain.invoke(
            {
                "user_query": user_query,
                "page_number": page_context.page,
                "page_markdown": page_context.markdown,
            }
        )

    def answer_from_pages(
        self,
        user_query: str,
        page_context: str,
        retrieval_trace: str,
    ) -> FinalAnswer:
        return self.answer_chain.invoke(
            {
                "user_query": user_query,
                "page_context": page_context,
                "retrieval_trace": retrieval_trace,
            }
        )

    def answer_from_compressed_evidence(
        self,
        user_query: str,
        compressed_evidence: str,
        retrieval_trace: str,
    ) -> FinalAnswer:
        return self.compressed_answer_chain.invoke(
            {
                "user_query": user_query,
                "compressed_evidence": compressed_evidence,
                "retrieval_trace": retrieval_trace,
            }
        )
