"""CSV-backed registries for backend MVP state."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from backend.config import get_storage_root

DOCUMENT_FIELDS = [
    "document_id",
    "document_type",
    "original_filename",
    "stored_pdf_path",
    "asset_root",
    "uploaded_at",
    "processing_status",
    "indexing_status",
    "ready_for_comparison",
    "page_count",
    "active_job_id",
    "error_message",
]

JOB_FIELDS = [
    "job_id",
    "job_type",
    "document_id",
    "comparison_id",
    "status",
    "started_at",
    "finished_at",
    "error_message",
    "log_path",
]

COMPARISON_FIELDS = [
    "comparison_id",
    "regulatory_document_id",
    "sop_document_id",
    "status",
    "created_at",
    "started_at",
    "finished_at",
    "report_json_path",
    "report_md_path",
    "error_message",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def storage_root() -> Path:
    root = get_storage_root()
    ensure_storage(root)
    return root


def ensure_storage(root: Path | None = None) -> Path:
    root = root or get_storage_root()
    (root / "registries").mkdir(parents=True, exist_ok=True)
    (root / "documents" / "regulatory").mkdir(parents=True, exist_ok=True)
    (root / "documents" / "sop").mkdir(parents=True, exist_ok=True)
    (root / "comparisons").mkdir(parents=True, exist_ok=True)
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    (root / "temp").mkdir(parents=True, exist_ok=True)
    _ensure_csv(document_registry_path(root), DOCUMENT_FIELDS)
    _ensure_csv(job_registry_path(root), JOB_FIELDS)
    _ensure_csv(comparison_registry_path(root), COMPARISON_FIELDS)
    return root


def document_registry_path(root: Path | None = None) -> Path:
    return (root or get_storage_root()) / "registries" / "document_registry.csv"


def job_registry_path(root: Path | None = None) -> Path:
    return (root or get_storage_root()) / "registries" / "job_registry.csv"


def comparison_registry_path(root: Path | None = None) -> Path:
    return (root or get_storage_root()) / "registries" / "comparison_registry.csv"


def document_root(document_type: str, document_id: str, root: Path | None = None) -> Path:
    return (root or get_storage_root()) / "documents" / document_type / document_id


def comparison_root(comparison_id: str, root: Path | None = None) -> Path:
    return (root or get_storage_root()) / "comparisons" / comparison_id


def _ensure_csv(path: Path, fields: list[str]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_rows(path, fields, [])


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def write_rows(path: Path, fields: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    with tmp_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "")) for field in fields})
    os.replace(tmp_path, path)


def _next_id(rows: list[dict[str, str]], id_field: str, prefix: str) -> str:
    max_value = 0
    for row in rows:
        value = row.get(id_field, "")
        if not value.startswith(f"{prefix}_"):
            continue
        try:
            max_value = max(max_value, int(value.rsplit("_", 1)[1]))
        except ValueError:
            continue
    return f"{prefix}_{max_value + 1:06d}"


def next_document_id(document_type: str) -> str:
    ensure_storage()
    prefix = "reg" if document_type == "regulatory" else "sop"
    return _next_id(read_rows(document_registry_path()), "document_id", prefix)


def next_job_id() -> str:
    ensure_storage()
    return _next_id(read_rows(job_registry_path()), "job_id", "job")


def next_comparison_id() -> str:
    ensure_storage()
    return _next_id(read_rows(comparison_registry_path()), "comparison_id", "cmp")


def read_documents() -> list[dict[str, str]]:
    ensure_storage()
    return read_rows(document_registry_path())


def write_documents(rows: list[dict[str, object]]) -> None:
    ensure_storage()
    write_rows(document_registry_path(), DOCUMENT_FIELDS, rows)


def get_document(document_id: str) -> dict[str, str] | None:
    for row in read_documents():
        if row["document_id"] == document_id:
            return row
    return None


def upsert_document(row: dict[str, object]) -> None:
    rows = read_documents()
    updated = False
    for index, existing in enumerate(rows):
        if existing["document_id"] == row["document_id"]:
            rows[index] = {**existing, **{key: str(value) for key, value in row.items()}}
            updated = True
            break
    if not updated:
        rows.append({key: str(value) for key, value in row.items()})
    write_documents(rows)


def read_jobs() -> list[dict[str, str]]:
    ensure_storage()
    return read_rows(job_registry_path())


def get_job(job_id: str) -> dict[str, str] | None:
    for row in read_jobs():
        if row["job_id"] == job_id:
            return row
    return None


def upsert_job(row: dict[str, object]) -> None:
    rows = read_jobs()
    updated = False
    for index, existing in enumerate(rows):
        if existing["job_id"] == row["job_id"]:
            rows[index] = {**existing, **{key: str(value) for key, value in row.items()}}
            updated = True
            break
    if not updated:
        rows.append({key: str(value) for key, value in row.items()})
    write_rows(job_registry_path(), JOB_FIELDS, rows)


def read_comparisons() -> list[dict[str, str]]:
    ensure_storage()
    return read_rows(comparison_registry_path())


def get_comparison(comparison_id: str) -> dict[str, str] | None:
    for row in read_comparisons():
        if row["comparison_id"] == comparison_id:
            return row
    return None


def upsert_comparison(row: dict[str, object]) -> None:
    rows = read_comparisons()
    updated = False
    for index, existing in enumerate(rows):
        if existing["comparison_id"] == row["comparison_id"]:
            rows[index] = {**existing, **{key: str(value) for key, value in row.items()}}
            updated = True
            break
    if not updated:
        rows.append({key: str(value) for key, value in row.items()})
    write_rows(comparison_registry_path(), COMPARISON_FIELDS, rows)
