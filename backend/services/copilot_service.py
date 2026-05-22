"""Backend wrapper for vectorless document co-pilot retrieval."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from backend.schemas import CopilotQueryRequest, CopilotQueryResponse
from backend.services import document_service
from document_retrieval.graph import run_document_retrieval


def query_document_copilot(
    document_id: str,
    request: CopilotQueryRequest,
) -> CopilotQueryResponse:
    document = document_service.get_document_or_404(document_id)
    if document.get("processing_status") != "completed" or document.get("indexing_status") != "completed":
        raise HTTPException(status_code=400, detail="Document must be processed and indexed before co-pilot queries")

    asset_root = Path(document["asset_root"])
    topic_index_path = asset_root / "indexing_output" / "topic_index.json"
    pages_folder_path = asset_root / "enriched_doc" / "pages_md"
    if not topic_index_path.exists():
        raise HTTPException(status_code=404, detail=f"Topic index not found for document: {document_id}")
    if not pages_folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Enriched pages folder not found for document: {document_id}")

    output = run_document_retrieval(
        user_query=request.query,
        topic_index_path=topic_index_path,
        pages_folder_path=pages_folder_path,
        max_direct_pages=request.max_direct_pages,
        max_direct_estimated_tokens=request.max_direct_estimated_tokens,
    )
    return CopilotQueryResponse(
        document_id=document_id,
        answer=output.final_answer.model_dump(mode="json"),
        retrieval_trace=output.retrieval_trace.model_dump(mode="json"),
        routing_decision=(
            output.routing_decision.model_dump(mode="json")
            if output.routing_decision is not None
            else None
        ),
        selected_pages=output.selected_pages,
        estimated_context_tokens=output.estimated_context_tokens,
        memory_mode=output.memory_mode,
        compressed_evidence=[
            item.model_dump(mode="json") for item in output.compressed_evidence
        ],
        debug_steps=output.debug_steps,
    )
