"""LangChain prompt templates for document comparison."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


COMPARISON_PLAN_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a regulatory-to-SOP comparison planner. "
                "You receive one SOP target page, optional next-page continuity context, "
                "a previous SOP page summary, and a regulatory topic index. "
                "Identify SOP topics, claims, procedural controls, responsibilities, records, "
                "timings, exceptions, and obligations on the target page. "
                "Map them to the minimum sufficient regulatory topics/pages. "
                "Do not perform final gap analysis. "
                "Use only regulatory topics and pages present in the topic index. "
                "Return structured output only."
            ),
        ),
        (
            "human",
            (
                "SOP target page number:\n{sop_page_number}\n\n"
                "SOP target page Markdown:\n{sop_page_markdown}\n\n"
                "SOP next page Markdown for continuity only:\n{sop_next_page_markdown}\n\n"
                "Previous SOP page summary/result:\n{previous_sop_page_summary}\n\n"
                "Regulatory topic index JSON:\n{regulatory_topic_index_json}\n\n"
                "Create a comparison plan for the SOP target page."
            ),
        ),
    ]
)


COMPRESS_REGULATORY_EVIDENCE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You compress regulatory page evidence for one SOP comparison item. "
                "Do not decide the gap. Extract only regulatory obligations, conditions, "
                "definitions, records, roles, timings, exceptions, and controls relevant "
                "to the SOP claim. Preserve page numbers and exact terms. "
                "Return structured output only."
            ),
        ),
        (
            "human",
            (
                "SOP claim/topic:\n{sop_claim}\n\n"
                "Comparison focus:\n{comparison_focus}\n\n"
                "Regulatory topic:\n{regulatory_topic}\n\n"
                "Regulatory page number:\n{regulatory_page_number}\n\n"
                "Regulatory page Markdown:\n{regulatory_page_markdown}\n\n"
                "Extract useful regulatory evidence."
            ),
        ),
    ]
)


GAP_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a regulatory gap analysis reviewer. "
                "Compare SOP evidence against regulatory evidence. "
                "Do not use outside knowledge. "
                "Classify the status as compliant, partially_compliant, missing, "
                "conflicting, not_applicable, or needs_human_review. "
                "Be conservative: if evidence is ambiguous, use needs_human_review. "
                "Return structured output only."
            ),
        ),
        (
            "human",
            (
                "SOP page: {sop_page}\n\n"
                "SOP topic:\n{sop_topic}\n\n"
                "SOP evidence:\n{sop_evidence}\n\n"
                "Mapped regulatory topics:\n{regulatory_topics}\n\n"
                "Regulatory evidence:\n{regulatory_evidence}\n\n"
                "Comparison focus:\n{comparison_focus}\n\n"
                "Perform the gap analysis."
            ),
        ),
    ]
)
