import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def fake_process_document(_pdf_path, output_root=None):
    root = Path(output_root)
    pages = root / "enriched_doc" / "pages_md"
    images = root / "docling_assets" / "page_images"
    pages.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    (pages / "page_0001.md").write_text("--- PAGE 1 ---\nPrepared evidence.", encoding="utf-8")
    (images / "page-1.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def fake_index_document(pages_folder_path, output_folder_path, document_id, **_kwargs):
    output_folder = Path(output_folder_path)
    output_folder.mkdir(parents=True, exist_ok=True)
    topic_index_path = output_folder / "topic_index.json"
    topic_index_path.write_text(
        json.dumps(
            [
                {
                    "topic": "Prepared evidence controls",
                    "pages": [1],
                    "description": "Regulatory evidence for prepared controls.",
                    "assets": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(
        topic_index_path=topic_index_path,
        processing_state_path=output_folder / "processing_state.json",
        revision_log_path=output_folder / "revision_log.md",
        validation_report_path=output_folder / "validation_report.json",
    )


def fake_compare_documents(regulatory_root, sop_root, comparison_run_dir, comparison_run_id, **_kwargs):
    run_dir = Path(comparison_run_dir)
    page_reports = run_dir / "page_reports"
    page_reports.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "comparison_id": comparison_run_id,
        "regulatory_document_id": Path(regulatory_root).name,
        "sop_document_id": Path(sop_root).name,
        "summary": {"total_pages": 1, "total_findings": 1},
        "page_reports": [
            {
                "sop_page": 1,
                "overall_status": "compliant",
                "what_went_right": ["SOP evidence is present."],
                "what_went_wrong": [],
                "human_review_items": [],
                "gap_items": [],
            }
        ],
    }
    final_report = run_dir / "final_report.json"
    final_markdown = run_dir / "final_report.md"
    final_csv = run_dir / "final_report.csv"
    page_report = page_reports / "sop_page_0001.json"
    final_report.write_text(json.dumps(report_payload), encoding="utf-8")
    final_markdown.write_text("# Final Report\n", encoding="utf-8")
    final_csv.write_text("comparison_id,sop_page,status\n", encoding="utf-8")
    page_report.write_text(json.dumps(report_payload["page_reports"][0]), encoding="utf-8")
    return SimpleNamespace(
        comparison_run_id=comparison_run_id,
        comparison_run_dir=run_dir,
        gap_report_path=final_report,
        markdown_report_path=final_markdown,
        executive_summary_path=run_dir / "executive_summary.md",
        page_result_paths=[page_report],
    )


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.temp_dir.name) / "storage"
        self.env_patch = patch.dict(
            os.environ,
            {"DOC_COMPARING_STORAGE_ROOT": str(self.storage_root)},
        )
        self.env_patch.start()
        self.client = TestClient(create_app())

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def upload_pdf(self, document_type: str, filename: str = "source.pdf") -> dict:
        response = self.client.post(
            "/documents/upload",
            data={"document_type": document_type},
            files={"file": (filename, b"%PDF-1.4\n", "application/pdf")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def process_document(self, document_id: str) -> dict:
        with patch(
            "backend.services.processing_service.run_document_processing",
            side_effect=fake_process_document,
        ):
            response = self.client.post(f"/documents/{document_id}/process")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def index_document(self, document_id: str) -> dict:
        with patch(
            "backend.services.indexing_service.run_indexing_pipeline",
            side_effect=fake_index_document,
        ):
            response = self.client.post(f"/documents/{document_id}/index")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_upload_documents_creates_storage_and_registry_rows(self):
        regulatory = self.upload_pdf("regulatory", "reg.pdf")
        sop = self.upload_pdf("sop", "sop.pdf")

        self.assertEqual(regulatory["document_id"], "reg_000001")
        self.assertEqual(sop["document_id"], "sop_000001")
        self.assertTrue(
            (
                self.storage_root
                / "documents"
                / "regulatory"
                / "reg_000001"
                / "original"
                / "source.pdf"
            ).exists()
        )

        rows = read_csv_rows(self.storage_root / "registries" / "document_registry.csv")
        self.assertEqual([row["document_id"] for row in rows], ["reg_000001", "sop_000001"])
        self.assertEqual(rows[0]["indexing_status"], "not_started")
        self.assertEqual(rows[1]["indexing_status"], "not_required")

    def test_upload_rejects_non_pdf(self):
        response = self.client.post(
            "/documents/upload",
            data={"document_type": "sop"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)

    def test_process_job_updates_sop_readiness_and_writes_manifest(self):
        sop = self.upload_pdf("sop")

        job = self.process_document(sop["document_id"])

        self.assertEqual(job["status"], "queued")
        job_status = self.client.get(f"/jobs/{job['job_id']}").json()
        self.assertEqual(job_status["status"], "completed")
        document = self.client.get("/documents", params={"document_type": "sop"}).json()["documents"][0]
        self.assertTrue(document["ready_for_comparison"])
        manifest_path = self.storage_root / "documents" / "sop" / sop["document_id"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["document_type"], "sop")
        self.assertEqual(manifest["total_pages"], 1)

    def test_indexing_rejects_sop_and_unprocessed_regulatory_document(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")

        unprocessed_response = self.client.post(f"/documents/{regulatory['document_id']}/index")
        sop_response = self.client.post(f"/documents/{sop['document_id']}/index")

        self.assertEqual(unprocessed_response.status_code, 400)
        self.assertEqual(sop_response.status_code, 400)

    def test_regulatory_indexing_writes_topic_index_path_and_readiness(self):
        regulatory = self.upload_pdf("regulatory")
        self.process_document(regulatory["document_id"])

        job = self.index_document(regulatory["document_id"])

        self.assertEqual(job["status"], "queued")
        job_status = self.client.get(f"/jobs/{job['job_id']}").json()
        self.assertEqual(job_status["status"], "completed")
        document = self.client.get(
            "/documents",
            params={"document_type": "regulatory"},
        ).json()["documents"][0]
        self.assertTrue(document["ready_for_comparison"])
        manifest_path = (
            self.storage_root
            / "documents"
            / "regulatory"
            / regulatory["document_id"]
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["topic_index_path"], "indexing_output/topic_index.json")

    def test_comparison_creation_writes_request_reports_and_registry(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])

        with patch(
            "backend.services.comparison_service.run_document_comparison",
            side_effect=fake_compare_documents,
        ):
            response = self.client.post(
                "/comparisons",
                json={
                    "regulatory_document_id": regulatory["document_id"],
                    "sop_document_id": sop["document_id"],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        comparison_id = payload["comparison_id"]
        comparison_root = self.storage_root / "comparisons" / comparison_id
        self.assertTrue((comparison_root / "comparison_request.json").exists())
        self.assertTrue((comparison_root / "final_report.json").exists())
        self.assertTrue((comparison_root / "final_report.csv").exists())

        status = self.client.get(f"/comparisons/{comparison_id}").json()
        self.assertEqual(status["status"], "completed")
        report = self.client.get(f"/comparisons/{comparison_id}/report").json()
        self.assertEqual(report["summary"]["total_findings"], 1)
        page = self.client.get(f"/comparisons/{comparison_id}/pages/1").json()
        self.assertEqual(page["sop_page"], 1)
        self.assertEqual(
            page["sop_page_image_url"],
            f"/assets/documents/{sop['document_id']}/page-image/1",
        )

    def test_asset_endpoint_returns_page_image_or_404(self):
        sop = self.upload_pdf("sop")
        self.process_document(sop["document_id"])

        found = self.client.get(f"/assets/documents/{sop['document_id']}/page-image/1")
        missing = self.client.get(f"/assets/documents/{sop['document_id']}/page-image/99")

        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.headers["content-type"], "image/png")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
