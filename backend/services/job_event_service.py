"""File-backed job event logging for long-running backend work."""

from __future__ import annotations

import json
from pathlib import Path

from backend.schemas import JobEvent, JobEventsResponse
from backend.services import registry


def _events_path(job_id: str) -> Path:
    root = registry.storage_root()
    return root / "jobs" / job_id / "events.jsonl"


def append_event(
    job_id: str,
    stage: str,
    step: str,
    message: str,
    progress_current: int | None = None,
    progress_total: int | None = None,
) -> JobEvent:
    event = JobEvent(
        timestamp=registry.utc_now(),
        job_id=job_id,
        stage=stage,
        step=step,
        message=message,
        progress_current=progress_current,
        progress_total=progress_total,
    )
    path = _events_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event.model_dump(), ensure_ascii=False) + "\n")
    return event


def read_events(job_id: str) -> JobEventsResponse:
    path = _events_path(job_id)
    events: list[JobEvent] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(JobEvent.model_validate_json(line))
    return JobEventsResponse(job_id=job_id, events=events)
