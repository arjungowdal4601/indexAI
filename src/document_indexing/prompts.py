"""LangChain prompt templates for topic indexing."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


TOPIC_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You build compact topic indexes for page-wise Markdown documents. "
                "Identify navigation-worthy topics in the main pages only. Use "
                "forward context only to understand continuity, not as indexed pages. "
                "Return topic names, main-window pages, useful descriptions, and "
                "as many navigation keywords as the topic genuinely needs. Do not "
                "pad the keyword list with filler or duplicate terms."
            ),
        ),
        (
            "human",
            (
                "Existing topic index summary:\n{existing_topic_summary}\n\n"
                "Main pages to index:\n{main_pages}\n\n"
                "Forward context pages for continuity only:\n{context_pages}\n\n"
                "Create topics, not page summaries. Do not include context-only page "
                "numbers in candidate pages."
            ),
        ),
    ]
)


TOPIC_MATCHING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "Decide whether each candidate topic updates an existing topic or "
                "should be added as a new topic. Match by meaning, description, "
                "keywords, and page proximity, not only exact title."
            ),
        ),
        (
            "human",
            (
                "Current topic index:\n{current_index}\n\n"
                "Candidate topics:\n{candidates}\n\n"
                "Return one decision for each candidate topic."
            ),
        ),
    ]
)


DESCRIPTION_UPDATE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "Rewrite an existing topic description into one compact improved "
                "navigation-focused description. Do not append mechanically. Keep "
                "the result factual and concise."
            ),
        ),
        (
            "human",
            (
                "Existing topic:\n{existing_topic}\n\n"
                "New candidate details:\n{candidate_topic}\n\n"
                "Return only the improved description in the schema."
            ),
        ),
    ]
)
