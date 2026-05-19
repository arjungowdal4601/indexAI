"""LangChain prompt templates for vectorless document retrieval."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


ROUTE_QUERY_TO_TOPICS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a topic router for a document retrieval system. "
                "You receive a user query and a topic index JSON. "
                "Select the minimum sufficient topics and pages needed to answer the full original query. "
                "Do not split the query into sub-questions. "
                "Use only topics and pages present in the topic index. "
                "Use rich descriptions and the assets field summaries as routing signals, "
                "especially when the query asks about a figure, table, formula, "
                "diagram, value, metric, or equation. "
                "Prefer precise page selection over broad selection. "
                "Return structured output only."
            ),
        ),
        (
            "human",
            (
                "User query:\n{user_query}\n\n"
                "Topic index JSON:\n{topic_index_json}\n\n"
                "Select the relevant topics and pages."
            ),
        ),
    ]
)


COMPRESS_PAGE_EVIDENCE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You compress selected page content for answering a user query. "
                "Extract only evidence useful for the original query. "
                "Do not answer the query yet. "
                "Preserve exact terms, values, conditions, exceptions, table meanings, figure meanings, and formula meanings. "
                "Keep the page number."
            ),
        ),
        (
            "human",
            (
                "User query:\n{user_query}\n\n"
                "Page number: {page_number}\n\n"
                "Page markdown:\n{page_markdown}\n\n"
                "Extract useful evidence for this query."
            ),
        ),
    ]
)


ANSWER_FROM_PAGES_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a grounded document QA assistant. "
                "Answer only from the selected page Markdown evidence. "
                "Do not use outside knowledge. "
                "Cite page numbers inline like [p. 4]. "
                "If the selected pages do not contain the answer, say what is missing. "
                "Return structured output only."
            ),
        ),
        (
            "human",
            (
                "User query:\n{user_query}\n\n"
                "Retrieval trace:\n{retrieval_trace}\n\n"
                "Selected page context:\n{page_context}\n\n"
                "Answer the query using only this evidence."
            ),
        ),
    ]
)


ANSWER_FROM_COMPRESSED_EVIDENCE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a grounded document QA assistant. "
                "Answer only from compressed page evidence. "
                "Do not use outside knowledge. "
                "Cite page numbers inline like [p. 4]. "
                "If the evidence is insufficient, say what is missing. "
                "Return structured output only."
            ),
        ),
        (
            "human",
            (
                "User query:\n{user_query}\n\n"
                "Retrieval trace:\n{retrieval_trace}\n\n"
                "Compressed evidence:\n{compressed_evidence}\n\n"
                "Answer the query using only this evidence."
            ),
        ),
    ]
)
