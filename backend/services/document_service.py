"""Document upload, listing, and manifest helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import HTTPException

from backend.schemas import DocumentResponse
from backend.services import registry


def _bool(value: object) -> bool:
    return str(value).lower() == "true"


def _document_response(row: dict[str, str]) -> DocumentResponse:
    page_count = row.get("page_count") or None
    return DocumentResponse(
        document_id=row["document_id"],
        document_type=row["document_type"],  # type: ignore[arg-type]
        filename=row["original_filename"],
        processing_status=row["processing_status"],
        indexing_status=row["indexing_status"],
        ready_for_comparison=_bool(row["ready_for_comparison"]),
        page_count=int(page_count) if page_count else None,
        active_job_id=row.get("active_job_id") or None,
        error_message=row.get("error_message") or None,
    )


def get_document_or_404(document_id: str) -> dict[str, str]:
    row = registry.get_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")
    return row


def list_documents(document_type: str | None = None) -> list[DocumentResponse]:
    rows = registry.read_documents()
    if document_type is not None:
        rows = [row for row in rows if row["document_type"] == document_type]
    return [_document_response(row) for row in rows]


def upload_document(document_type: str, original_filename: str, content: bytes) -> DocumentResponse:
    if document_type not in {"regulatory", "sop"}:
        raise HTTPException(status_code=400, detail="document_type must be regulatory or sop")
    if not original_filename.lower().endswith(".pdf") or not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    root = registry.storage_root()
    document_id = registry.next_document_id(document_type)
    asset_root = registry.document_root(document_type, document_id, root)
    original_dir = asset_root / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    stored_pdf_path = original_dir / "source.pdf"
    stored_pdf_path.write_bytes(content)

    row = {
        "document_id": document_id,
        "document_type": document_type,
        "original_filename": original_filename,
        "stored_pdf_path": stored_pdf_path,
        "asset_root": asset_root,
        "uploaded_at": registry.utc_now(),
        "processing_status": "not_started",
        "indexing_status": "not_started",
        "ready_for_comparison": "false",
        "page_count": "",
        "active_job_id": "",
        "error_message": "",
    }
    registry.upsert_document(row)
    return _document_response({key: str(value) for key, value in row.items()})


def manifest_path(document_row: dict[str, str]) -> Path:
    return Path(document_row["asset_root"]) / "manifest.json"


def write_manifest(document_row: dict[str, str], total_pages: int, topic_index_path: str | None = None) -> Path:
    root = Path(document_row["asset_root"])
    payload = {
        "document_id": document_row["document_id"],
        "document_type": document_row["document_type"],
        "source_file": "original/source.pdf",
        "enriched_pages_folder": "enriched_doc/pages_md",
        "page_images_folder": "docling_assets/page_images",
        "total_pages": total_pages,
    }
    if topic_index_path:
        payload["topic_index_path"] = topic_index_path
    path = root / "manifest.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def update_manifest_topic_index(document_row: dict[str, str], topic_index_path: str) -> None:
    path = manifest_path(document_row)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["topic_index_path"] = topic_index_path
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def copy_existing_asset_root(source_root: Path, destination_root: Path) -> None:
    if destination_root.exists():
        shutil.rmtree(destination_root)
    shutil.copytree(source_root, destination_root)
