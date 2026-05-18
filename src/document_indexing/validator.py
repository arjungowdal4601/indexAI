"""Deterministic validation and cleanup for topic indexes."""

from __future__ import annotations

import json
import re
from collections import Counter

from .schemas import TopicEntry, ValidationReport

def estimate_tokens(payload: object) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    return max(1, len(text) // 4)


def _clean_keywords(keywords: list[str]) -> tuple[list[str], bool]:
    cleaned = []
    seen = set()
    changed = False
    for keyword in keywords:
        normalized = re.sub(r"\s+", " ", keyword.strip())
        if not normalized:
            changed = True
            continue
        key = normalized.lower()
        if key in seen:
            changed = True
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned, changed


def _normalize_topic_key(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", topic.lower()).strip()


def validate_topic_index(
    topics: list[TopicEntry],
    token_limit: int,
) -> tuple[ValidationReport, list[TopicEntry]]:
    warnings: list[str] = []
    fixes: list[str] = []
    cleaned_topics: list[TopicEntry] = []

    for topic in topics:
        pages = sorted(set(int(page) for page in topic.pages))
        if pages != topic.pages:
            fixes.append(f"normalized_pages: {topic.topic}")

        keywords, keywords_changed = _clean_keywords(topic.keywords)
        if keywords_changed:
            fixes.append(f"cleaned_keywords: {topic.topic}")

        description = re.sub(r"\s+", " ", topic.description.strip())
        if description != topic.description:
            fixes.append(f"cleaned_description: {topic.topic}")
        cleaned_topics.append(
            TopicEntry(
                topic=topic.topic.strip(),
                pages=pages,
                description=description,
                keywords=keywords,
            )
        )

    topic_keys = [_normalize_topic_key(topic.topic) for topic in cleaned_topics]
    for key, count in Counter(topic_keys).items():
        if key and count > 1:
            warnings.append(f"near_duplicate_topics: {key}")

    estimated = estimate_tokens([topic.model_dump(mode="json") for topic in cleaned_topics])
    if estimated > token_limit:
        warnings.append("token_budget_exceeded")

    failures = []
    for topic in cleaned_topics:
        if not topic.topic:
            failures.append("empty_topic")
        if not topic.pages:
            failures.append(f"empty_pages: {topic.topic}")
        if not topic.description:
            failures.append(f"empty_description: {topic.topic}")
        if not topic.keywords:
            warnings.append(f"empty_keywords: {topic.topic}")

    status = "failed" if failures else "passed"
    warnings.extend(failures)
    return (
        ValidationReport(
            status=status,
            warnings=warnings,
            fixes_applied=fixes,
            estimated_tokens=estimated,
        ),
        cleaned_topics,
    )
