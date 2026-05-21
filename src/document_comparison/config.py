"""Configuration defaults for document comparison."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_COMPARISON_RUNS_DIR = PROJECT_ROOT / "data" / "comparison_runs"
DEFAULT_COMPARISON_MODEL = "gpt-5.4-mini"
DEFAULT_PLANNER_REASONING_EFFORT = "high"
DEFAULT_EXECUTOR_REASONING_EFFORT = "medium"
DEFAULT_MAX_DIRECT_REGULATORY_PAGES = 8
DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS = 70000
DEFAULT_SOP_CONTEXT_FORWARD_PAGES = 1


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
