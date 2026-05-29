"""LLM client protocol and OpenAI-backed implementation for enrichment."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from .prompts import (
    FORMULA_PROMPT,
    PICTURE_PROMPT,
    build_table_context,
    build_table_prompt,
)

DEFAULT_ENRICHMENT_MODEL = "gpt-5.4-mini"


@dataclass(frozen=True)
class TableDescriptionRequest:
    table_id: str
    page_no: int
    current_markdown: str
    current_image_path: Path


class EnrichmentClient(Protocol):
    def describe_table(self, request: TableDescriptionRequest) -> str:
        ...

    def describe_image(self, image_path: Path) -> str:
        ...

    def describe_formula(self, image_path: Path, formula_markdown: str) -> str:
        ...


def encode_image_to_base64(image_path: Path) -> str:
    with image_path.open("rb") as file:
        return base64.b64encode(file.read()).decode("utf-8")


def response_text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


class OpenAIEnrichmentClient:
    def __init__(self, model: Optional[str] = None):
        try:
            from dotenv import load_dotenv
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Document enrichment requires python-dotenv and langchain-openai. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for document enrichment. "
                "Phase 1 artifacts are available; set OPENAI_API_KEY and rerun python main.py."
            )

        self.llm = ChatOpenAI(
            api_key=api_key,
            model=model
            or os.getenv("DOC_ENRICHMENT_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_ENRICHMENT_MODEL,
        )

    def _image_base64(self, image_path: Path) -> str:
        return encode_image_to_base64(image_path)

    def describe_table(self, request: TableDescriptionRequest) -> str:
        table_context = build_table_context(
            table_id=request.table_id,
            page_no=request.page_no,
            current_markdown=request.current_markdown,
        )
        current_image_base64 = self._image_base64(request.current_image_path)
        prompt = build_table_prompt(include_current_image=True)
        inputs = {
            "table_context": table_context,
            "current_image_base64": current_image_base64,
        }

        chain = prompt | self.llm
        response = chain.invoke(inputs)
        return response_text(response)

    def describe_image(self, image_path: Path) -> str:
        chain = PICTURE_PROMPT | self.llm
        response = chain.invoke({"image_base64": self._image_base64(image_path)})
        return response_text(response)

    def describe_formula(self, image_path: Path, formula_markdown: str) -> str:
        chain = FORMULA_PROMPT | self.llm
        response = chain.invoke(
            {
                "image_base64": self._image_base64(image_path),
                "formula_markdown": formula_markdown,
            }
        )
        return response_text(response)
