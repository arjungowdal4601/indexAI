"""LangChain prompt templates for topic indexing."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


TOPIC_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You build compact topic indexes for page-wise Markdown documents. "
                "You index only the target page from the JSON payload. Use previous "
                "page topics only as continuity hints; when target-page content "
                "continues a previous topic, reuse the same topic name when "
                "appropriate. Use next page Markdown only for continuation or "
                "boundary context. Never include previous or next page numbers in "
                "the returned topic text. Return topic names, rich evidence-dense "
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
                "Payload:\n{payload}\n\n"
                "Create topics, not page summaries. Candidate asset_paths must "
                "contain only paths listed in target_page_assets."
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
                "has no match in this batch. Use only the candidate and existing "
                "topic names and descriptions in the JSON payload. Return one "
                "decision for each candidate slot. For updates, set matched_batch_slot "
                "to the existing topic slot. If no existing topic in this batch "
                "matches, return no_match and leave matched_batch_slot null. Do not "
                "use free-text topic names as match targets."
            ),
        ),
        (
            "human",
            (
                "Payload:\n{payload}\n\n"
                "Return one structured decision for each candidate."
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
                "New candidate details:\n{new_candidate}\n\n"
                "Return only the improved description in the schema."
            ),
        ),
    ]
)
