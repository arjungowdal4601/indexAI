"""Shared retry helpers for transient LLM/API failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

TRANSIENT_ERROR_KEYWORDS = (
    "timeout",
    "timed out",
    "rate limit",
    "ratelimit",
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection",
    "connecterror",
    "temporarily",
    "service unavailable",
    "server error",
    "api error",
    "completion",
)

NON_TRANSIENT_ERROR_KEYWORDS = (
    "validationerror",
    "outputparserexception",
    "schema is invalid",
    "invalid schema",
)


def is_transient_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(keyword in text for keyword in NON_TRANSIENT_ERROR_KEYWORDS):
        return False
    return any(keyword in text for keyword in TRANSIENT_ERROR_KEYWORDS)


def run_with_retries(
    func: Callable[[], T],
    *,
    max_attempts: int = 3,
    initial_delay_seconds: float = 2.0,
    max_delay_seconds: float = 30.0,
    on_wait: Callable[[int, float, Exception], None] | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    last_error: Exception | None = None
    delay = initial_delay_seconds
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not is_transient_error(exc):
                raise
            if on_retry:
                on_retry(attempt, exc)
            if on_wait:
                on_wait(attempt, delay, exc)
            if delay > 0:
                time.sleep(delay)
            delay = min(delay * 2, max_delay_seconds)
    assert last_error is not None
    raise last_error
