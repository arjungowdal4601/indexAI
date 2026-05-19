"""LangChain prompt templates for topic indexing."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


TOPIC_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You build compact topic indexes for page-wise Markdown documents. "
                "You index only the target page. Use previous page indexed topics "
                "only as continuity hints for whether target-page content continues "
                "an existing topic. Use next page Markdown only for continuation or "
                "boundary context. Never include previous or next page numbers in "
                "candidate pages. Return topic names, rich evidence-dense "
                "descriptions, and asset_paths selected only from the provided "
                "target-page assets. Do not return keywords. Descriptions should be "
                "one to three sentences and include exact meaningful terms, "
                "abbreviations, formulas, values, distinctions, or table names only "
                "when they are essential to the topic. Avoid generic tag-cloud words. "
                "Use generic document evidence only; do not rely on examples from any "
                "known document."
            ),
        ),
        (
            "human",
            (
                "Existing topic index summary:\n{existing_topic_summary}\n\n"
                "Previous page number:\n{previous_page_number}\n\n"
                "Previous page indexed topics:\n{previous_page_indexed_topics}\n\n"
                "Target page number:\n{target_page_number}\n\n"
                "Target page Markdown:\n{target_page_markdown}\n\n"
                "Target page assets available for asset_paths:\n{target_page_assets}\n\n"
                "Next page number:\n{next_page_number}\n\n"
                "Next page Markdown:\n{next_page_markdown}\n\n"
                "Create topics, not page summaries. Candidate pages must contain "
                "only the target page number. Candidate asset_paths must contain only "
                "paths listed in target page assets."
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
                "asset-backed evidence, and page proximity, not only exact title."
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
                "the result factual, concise, and rich enough for routing. Preserve "
                "exact meaningful terms, abbreviations, formulas, values, distinctions, "
                "and asset-backed facts when they are essential to the topic."
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
