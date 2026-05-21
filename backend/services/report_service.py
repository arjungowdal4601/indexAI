"""Read comparison reports for API responses."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

from backend.services import comparison_service, document_service, registry


def read_comparison_report(comparison_id: str) -> dict:
    row = comparison_service.get_comparison_row_or_404(comparison_id)
    report_path = Path(row.get("report_json_path") or registry.comparison_root(comparison_id) / "final_report.json")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Comparison report not found: {comparison_id}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def read_page_report(comparison_id: str, sop_page_number: int) -> dict:
    comparison = comparison_service.get_comparison_row_or_404(comparison_id)
    run_dir = registry.comparison_root(comparison_id)
    path = run_dir / "page_reports" / f"sop_page_{int(sop_page_number):04d}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"SOP page report not found: {sop_page_number}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    sop = document_service.get_document_or_404(comparison["sop_document_id"])
    image_path = Path(sop["asset_root"]) / "docling_assets" / "page_images" / f"page-{int(sop_page_number)}.png"
    payload["sop_page_image_url"] = (
        f"/assets/documents/{sop['document_id']}/page-image/{int(sop_page_number)}"
    )
    if not image_path.exists():
        payload["image_warning"] = f"SOP page image not found for page {int(sop_page_number)}"
    return payload
