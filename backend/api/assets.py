"""Asset serving API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.services import document_service

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/documents/{document_id}/page-image/{page_number}")
def get_page_image(document_id: str, page_number: int) -> FileResponse:
    document = document_service.get_document_or_404(document_id)
    image_path = document_service.page_images_folder(document) / f"page-{int(page_number)}.png"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail=f"Page image not found: {page_number}")
    return FileResponse(image_path, media_type="image/png")
