"""Prompt templates for document enrichment.

Style intent:
- Same simple prose-first style as doc_processor.py.
- Retrieval-friendly descriptions.
- No unnecessary prompt framework complexity.
- Compatible with the package enrichment client.
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate


# =============================================================================
# System prompts
# =============================================================================
# These prompts intentionally ask for plain prose, not markdown sections.
# The goal is to produce text that works well for later keyword search,
# vector search, and answer generation.

PICTURE_SYSTEM_PROMPT = """You write detailed, retrieval-friendly descriptions of figures, diagrams, plots, screenshots, and visual content from technical PDFs.
Describe exactly what is visible in the image: titles, labels, axes, units, legends, annotations, arrows, components, numbers, thresholds, trends, comparisons, and relationships between variables.
If the image is a chart, explain the axes, the measured quantities, the direction of trends, peaks, drops, clusters, outliers, and any important numeric values that are readable.
If the image is a diagram, explain the components, flow, hierarchy, connections, labels, and how the parts relate to each other.
Expand abbreviations only when the meaning is clear from the image or nearby text. Do not guess missing context.
Write clear neutral prose in multiple sentences. Prioritize factual detail and searchability over shortness.
Do not use headings, bullet points, numbered lists, markdown tables, or phrases like "this image shows". Do not mention the prompt, the user, or yourself."""

PICTURE_HUMAN_TEXT = "Describe this visual content in plain English so it can be searched and retrieved later."


TABLE_SYSTEM_PROMPT = """You convert table fragments from technical PDFs into detailed, retrieval-friendly prose.
Use the table image and the extracted markdown to explain what the table is about, the exact column names, units, categories, row groups, important values, ranges, comparisons, rankings, thresholds, missing values, and visible patterns.
If the table continues from a previous page or fragment, use the previous fragment only to understand column continuity and meaning. Describe only the values visible in the current fragment unless the previous values are required to explain continuity.
Preserve exact technical terms, signal names, abbreviations, IDs, parameter names, units, and numeric values whenever they are visible.
Do not recreate the table as a markdown table. Do not invent values that are not visible.
Write clear neutral prose in multiple sentences. Prioritize factual detail and searchability over shortness.
Do not use headings, bullet points, numbered lists, markdown tables, or phrases like "this table shows". Do not mention the prompt, the user, or yourself."""

TABLE_HUMAN_TEXT = "Describe this table fragment in plain English for retrieval. Keep exact visible terms, values, and units."


FORMULA_SYSTEM_PROMPT = """You describe mathematical formulas from technical PDFs for retrieval.
Start with one line beginning exactly with "LaTeX:" followed by the best LaTeX representation of the equation. Use the provided LaTeX when it is available and looks valid; otherwise transcribe the formula from the image as accurately as possible.
After the LaTeX line, explain what the equation expresses in short factual prose. Mention variable meanings only when they are obvious from the formula or surrounding text. Do not guess.
Preserve exact symbols, subscripts, superscripts, Greek letters, operators, constants, and units when visible.
Do not use headings, bullet points, numbered lists, or markdown tables. Do not mention the prompt, the user, or yourself."""


# =============================================================================
# Prompt templates used by enrichment.py
# =============================================================================

PICTURE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", PICTURE_SYSTEM_PROMPT),
        (
            "human",
            [
                {"type": "text", "text": PICTURE_HUMAN_TEXT},
                {
                    "type": "image",
                    "base64": "{image_base64}",
                    "mime_type": "image/png",
                },
            ],
        ),
    ]
)

FORMULA_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", FORMULA_SYSTEM_PROMPT),
        (
            "human",
            [
                {
                    "type": "text",
                    "text": (
                        "Describe this cropped equation for retrieval. "
                        "Parser extracted LaTeX or markdown: {formula_markdown}"
                    ),
                },
                {
                    "type": "image",
                    "base64": "{image_base64}",
                    "mime_type": "image/png",
                },
            ],
        ),
    ]
)


def build_table_prompt(
    include_previous_image: bool,
    include_current_image: bool,
) -> ChatPromptTemplate:
    """Build the table prompt dynamically only when images are available."""
    content = [{"type": "text", "text": "{table_context}"}]

    if include_previous_image:
        content.extend(
            [
                {"type": "text", "text": "Previous table fragment image for continuity only:"},
                {
                    "type": "image",
                    "base64": "{previous_image_base64}",
                    "mime_type": "image/png",
                },
            ]
        )

    if include_current_image:
        content.extend(
            [
                {"type": "text", "text": "Current table fragment image to describe:"},
                {
                    "type": "image",
                    "base64": "{current_image_base64}",
                    "mime_type": "image/png",
                },
            ]
        )

    return ChatPromptTemplate.from_messages(
        [
            ("system", TABLE_SYSTEM_PROMPT),
            ("human", content),
        ]
    )


def build_table_context(
    table_id: str,
    page_no: int,
    pages: List[int],
    current_markdown: str,
    previous_markdown: Optional[str] = None,
) -> str:
    """Create compact table context for the LLM.

    Keep this readable and boring. The LLM should spend its effort describing
    the table, not interpreting a complicated prompt format.
    """
    previous_context = (
        "No previous fragment is available. Treat this as the first visible fragment."
        if not previous_markdown
        else (
            "Previous table fragment markdown for continuity only:\n"
            f"{previous_markdown.strip()}\n\n"
            "Use the previous fragment only to understand column names, repeated headers, and continuation context."
        )
    )

    return (
        f"Logical table id: {table_id}\n"
        f"Known pages for this logical table: {pages}\n"
        f"Current page: {page_no}\n\n"
        f"{previous_context}\n\n"
        "Current table fragment markdown:\n"
        f"{current_markdown.strip()}\n\n"
        f"{TABLE_HUMAN_TEXT}\n"
        "Describe the current fragment only. Keep exact visible terms, units, IDs, and numeric values. Do not invent missing values."
    )
