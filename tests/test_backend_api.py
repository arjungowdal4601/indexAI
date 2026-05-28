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
from backend.services import job_event_service, registry
from document_retrieval.schemas import FinalAnswer, RetrievalOutput, RetrievalTrace


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def has_hidden_chain_of_thought_key(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in {"chain_of_thought", "hidden_chain_of_thought"}:
                return True
            if has_hidden_chain_of_thought_key(item):
                return True
    elif isinstance(value, list):
        return any(has_hidden_chain_of_thought_key(item) for item in value)
    return False


def fake_process_document(_pdf_path, output_root=None, event_callback=None, **_kwargs):
    root = Path(output_root)
    pages = root / "enriched_doc" / "pages_md"
    images = root / "docling_assets" / "page_images"
    pages.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    (pages / "page_0001.md").write_text("--- PAGE 1 ---\nPrepared evidence.", encoding="utf-8")
    (root / "enriched_doc" / "readable_processed_doc.md").write_text(
        "--- PAGE 1 ---\nPrepared evidence.",
        encoding="utf-8",
    )
    for folder_name in ["image_png_images", "table_images", "formula_images"]:
        enriched_folder = root / "enriched_doc" / folder_name
        enriched_folder.mkdir(parents=True, exist_ok=True)
        (enriched_folder / "asset-1.png").write_bytes(b"asset")
        raw_folder = root / "docling_assets" / folder_name
        raw_folder.mkdir(parents=True, exist_ok=True)
        (raw_folder / "asset-1.png").write_bytes(b"asset")
    raw_pages = root / "docling_assets" / "pages_md"
    raw_pages.mkdir(parents=True, exist_ok=True)
    (raw_pages / "page_0001.md").write_text("--- PAGE 1 ---\nRaw evidence.", encoding="utf-8")
    (root / "docling_assets" / "stitched_raw_docling_markdown.md").write_text(
        "--- PAGE 1 ---\nRaw evidence.",
        encoding="utf-8",
    )
    (root / "docling_assets" / "table_continuity_map.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (images / "page-1.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    if event_callback:
        event_callback("document_processing", "processing_page", "Processing page 1 of 1", 1, 1)


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
    (output_folder / "processing_state.json").write_text("{}", encoding="utf-8")
    (output_folder / "validation_report.json").write_text("{}", encoding="utf-8")
    (output_folder / "revision_log.md").write_text("revision", encoding="utf-8")
    backup_dir = output_folder / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "topic_index_before_step_0001.json").write_text("[]", encoding="utf-8")
    return SimpleNamespace(
        topic_index_path=topic_index_path,
        processing_state_path=output_folder / "processing_state.json",
        revision_log_path=output_folder / "revision_log.md",
        validation_report_path=output_folder / "validation_report.json",
    )


def fake_compare_documents(regulatory_root, sop_root, comparison_run_dir, comparison_run_id, **_kwargs):
    event_callback = _kwargs.get("event_callback")
    if event_callback:
        event_callback(
            "comparison",
            "plan_sop_page",
            "Planning comparison for SOP page 1.",
            1,
            1,
        )
    run_dir = Path(comparison_run_dir)
    page_reports = run_dir / "page_reports"
    page_reports.mkdir(parents=True, exist_ok=True)
    for folder in [
        "plans",
        "item_results",
        "traces",
        "evidence/sop_page_0001",
        "page_results",
        "cache/regulatory_page_evidence",
        "reports",
        "state",
        "logs",
    ]:
        (run_dir / folder).mkdir(parents=True, exist_ok=True)
    (run_dir / "plans" / "sop_page_0001_plan.json").write_text("{}", encoding="utf-8")
    (run_dir / "item_results" / "sop_page_0001_item_001.json").write_text("{}", encoding="utf-8")
    (run_dir / "traces" / "sop_page_0001_trace.json").write_text("{}", encoding="utf-8")
    (run_dir / "evidence" / "sop_page_0001" / "regulatory_pages_item_001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (run_dir / "page_results" / "sop_page_0001.json").write_text("{}", encoding="utf-8")
    (run_dir / "cache" / "regulatory_page_evidence" / "page_0001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (run_dir / "state" / "comparison_state.json").write_text("{}", encoding="utf-8")
    (run_dir / "logs" / "run_log.csv").write_text("log\n", encoding="utf-8")
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
                "gap_items": [
                    {
                        "sop_page": 1,
                        "sop_topic": "Prepared evidence controls",
                        "regulatory_topics": ["Prepared evidence controls"],
                        "regulatory_pages_used": [1],
                        "status": "compliant",
                        "severity": "minor",
                        "confidence": "high",
                        "sop_evidence": "Prepared evidence.",
                        "regulatory_evidence": "Regulatory evidence.",
                        "gap_explanation": "The SOP covers the requirement.",
                        "recommended_action": "No action required.",
                        "missing_or_weak_elements": [],
                    }
                ],
            }
        ],
    }
    final_report = run_dir / "final_report.json"
    final_markdown = run_dir / "final_report.md"
    final_csv = run_dir / "final_report.csv"
    executive_summary = run_dir / "reports" / "executive_summary.md"
    duplicate_gap_report = run_dir / "reports" / "gap_report.json"
    page_report = page_reports / "sop_page_0001.json"
    final_report.write_text(json.dumps(report_payload), encoding="utf-8")
    final_markdown.write_text("# Final Report\n", encoding="utf-8")
    final_csv.write_text("comparison_id,sop_page,status\n", encoding="utf-8")
    executive_summary.write_text("# Executive Summary\n", encoding="utf-8")
    duplicate_gap_report.write_text(json.dumps(report_payload), encoding="utf-8")
    page_report.write_text(json.dumps(report_payload["page_reports"][0]), encoding="utf-8")
    return SimpleNamespace(
        comparison_run_id=comparison_run_id,
        comparison_run_dir=run_dir,
        gap_report_path=final_report,
        markdown_report_path=final_markdown,
        executive_summary_path=executive_summary,
        page_result_paths=[page_report],
    )


def fake_compare_documents_connection_error(regulatory_root, sop_root, comparison_run_dir, comparison_run_id, **_kwargs):
    run_dir = Path(comparison_run_dir)
    state_dir = run_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "comparison_state.json").write_text(
        json.dumps(
            {
                "comparison_run_id": comparison_run_id,
                "last_completed_sop_page": 3,
                "current_sop_page": 4,
                "completed_item_result_paths": [],
                "completed_page_result_paths": [],
                "status": "in_progress",
            }
        ),
        encoding="utf-8",
    )
    raise RuntimeError("Connection error.")


def fake_retrieve_document(**_kwargs):
    return RetrievalOutput(
        final_answer=FinalAnswer(
            answer="Co-pilot answer [p. 1].",
            pages_used=[1],
            missing_information=[],
        ),
        retrieval_trace=RetrievalTrace(
            matched_topics=["Prepared evidence controls"],
            pages_read=[1],
            files_read=["page_0001.md"],
            memory_mode="direct",
            selection_reason="Selected the matching prepared evidence topic.",
        ),
        selected_pages=[1],
        estimated_context_tokens=12,
        memory_mode="direct",
        debug_steps=[
            {
                "step": "answer",
                "status": "completed",
                "summary": "Generated a co-pilot answer.",
            }
        ],
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
        self.assertEqual(rows[1]["indexing_status"], "not_started")
        self.assertIn("active_job_id", rows[0])
        self.assertEqual(rows[0]["active_job_id"], "")
        self.assertIsNone(regulatory["active_job_id"])

    def test_document_response_includes_active_job_id(self):
        sop = self.upload_pdf("sop")

        document = self.client.get("/documents", params={"document_type": "sop"}).json()["documents"][0]

        self.assertIn("active_job_id", document)
        self.assertIsNone(document["active_job_id"])

    def test_upload_rejects_non_pdf(self):
        response = self.client.post(
            "/documents/upload",
            data={"document_type": "sop"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)

    def test_process_job_keeps_sop_not_ready_and_writes_manifest(self):
        sop = self.upload_pdf("sop")

        job = self.process_document(sop["document_id"])

        self.assertEqual(job["status"], "queued")
        job_status = self.client.get(f"/jobs/{job['job_id']}").json()
        self.assertEqual(job_status["status"], "completed")
        document = self.client.get("/documents", params={"document_type": "sop"}).json()["documents"][0]
        self.assertFalse(document["ready_for_comparison"])
        self.assertEqual(document["indexing_status"], "not_started")
        manifest_path = self.storage_root / "documents" / "sop" / sop["document_id"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["document_type"], "sop")
        self.assertEqual(manifest["total_pages"], 1)

    def test_indexing_rejects_unprocessed_documents(self):
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

    def test_sop_indexing_writes_topic_index_path_and_readiness(self):
        sop = self.upload_pdf("sop")
        self.process_document(sop["document_id"])

        job = self.index_document(sop["document_id"])

        self.assertEqual(job["job_type"], "index_document")
        job_status = self.client.get(f"/jobs/{job['job_id']}").json()
        self.assertEqual(job_status["status"], "completed")
        document = self.client.get(
            "/documents",
            params={"document_type": "sop"},
        ).json()["documents"][0]
        self.assertTrue(document["ready_for_comparison"])
        manifest_path = self.storage_root / "documents" / "sop" / sop["document_id"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["topic_index_path"], "indexing_output/topic_index.json")

    def test_indexing_cleanup_preserves_page_image_endpoint_and_copilot_inputs(self):
        sop = self.upload_pdf("sop")
        self.process_document(sop["document_id"])

        self.index_document(sop["document_id"])

        root = self.storage_root / "documents" / "sop" / sop["document_id"]
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["page_images_folder"], "page_images")
        self.assertTrue((root / "page_images" / "page-1.png").exists())
        self.assertFalse((root / "docling_assets").exists())
        self.assertTrue((root / "enriched_doc" / "pages_md" / "page_0001.md").exists())
        self.assertTrue((root / "indexing_output" / "topic_index.json").exists())

        response = self.client.get(f"/assets/documents/{sop['document_id']}/page-image/1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

    def test_prepare_endpoint_queues_prepare_document_job(self):
        sop = self.upload_pdf("sop")

        with patch(
            "backend.services.processing_service.run_document_processing",
            side_effect=fake_process_document,
        ), patch(
            "backend.services.indexing_service.run_indexing_pipeline",
            side_effect=fake_index_document,
        ):
            response = self.client.post(f"/documents/{sop['document_id']}/prepare")

        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        self.assertEqual(job["job_type"], "prepare_document")
        self.assertEqual(job["document_id"], sop["document_id"])
        document = self.client.get("/documents", params={"document_type": "sop"}).json()["documents"][0]
        self.assertEqual(document["active_job_id"], job["job_id"])
        self.assertTrue(document["ready_for_comparison"])
        self.assertEqual(document["processing_status"], "completed")
        self.assertEqual(document["indexing_status"], "completed")

    def test_prepare_job_runs_processing_then_indexing(self):
        sop = self.upload_pdf("sop")
        calls = []

        def process_then_record(*args, **kwargs):
            calls.append("process")
            return fake_process_document(*args, **kwargs)

        def index_then_record(*args, **kwargs):
            calls.append("index")
            return fake_index_document(*args, **kwargs)

        with patch(
            "backend.services.processing_service.run_document_processing",
            side_effect=process_then_record,
        ), patch(
            "backend.services.indexing_service.run_indexing_pipeline",
            side_effect=index_then_record,
        ):
            response = self.client.post(f"/documents/{sop['document_id']}/prepare")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls, ["process", "index"])

    def test_prepare_retry_resumes_failed_processing(self):
        sop = self.upload_pdf("sop")
        document = registry.get_document(sop["document_id"])
        registry.upsert_document(
            {
                **document,
                "processing_status": "failed",
                "indexing_status": "not_started",
                "ready_for_comparison": "false",
                "error_message": "Connection timeout",
            }
        )

        with patch(
            "backend.services.processing_service.run_document_processing",
            side_effect=fake_process_document,
        ) as process_document, patch(
            "backend.services.indexing_service.run_indexing_pipeline",
            side_effect=fake_index_document,
        ):
            response = self.client.post(f"/documents/{sop['document_id']}/prepare")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(process_document.call_args.kwargs["resume"])

    def test_prepare_rejects_already_ready_document(self):
        sop = self.upload_pdf("sop")
        self.process_document(sop["document_id"])
        self.index_document(sop["document_id"])

        response = self.client.post(f"/documents/{sop['document_id']}/prepare")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Document is already indexed", response.text)

    def test_prepare_rejects_duplicate_running_prepare(self):
        sop = self.upload_pdf("sop")
        job = registry.next_job_id()
        registry.upsert_job(
            {
                "job_id": job,
                "job_type": "prepare_document",
                "document_id": sop["document_id"],
                "comparison_id": "",
                "status": "running",
                "started_at": "",
                "finished_at": "",
                "error_message": "",
                "log_path": "",
            }
        )
        document = registry.get_document(sop["document_id"])
        registry.upsert_document({**document, "active_job_id": job})

        response = self.client.post(f"/documents/{sop['document_id']}/prepare")

        self.assertEqual(response.status_code, 400)
        self.assertIn("already running", response.text)

    def test_comparison_creation_writes_request_reports_and_registry(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])
        self.index_document(sop["document_id"])

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
        self.assertTrue((comparison_root / "reports" / "executive_summary.md").exists())
        self.assertTrue((comparison_root / "artifact_cleanup.json").exists())
        self.assertFalse((comparison_root / "plans").exists())
        self.assertFalse((comparison_root / "item_results").exists())
        self.assertFalse((comparison_root / "traces").exists())
        self.assertFalse((comparison_root / "evidence").exists())
        self.assertFalse((comparison_root / "page_results").exists())
        self.assertFalse((comparison_root / "cache").exists())

        status = self.client.get(f"/comparisons/{comparison_id}").json()
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["progress_message"], "Comparison complete.")
        self.assertEqual(status["progress_current"], 1)
        self.assertEqual(status["progress_total"], 1)
        report = self.client.get(f"/comparisons/{comparison_id}/report").json()
        self.assertEqual(report["summary"]["total_findings"], 1)
        page = self.client.get(f"/comparisons/{comparison_id}/pages/1").json()
        self.assertEqual(page["sop_page"], 1)
        self.assertEqual(
            page["sop_page_image_url"],
            f"/assets/documents/{sop['document_id']}/page-image/1",
        )
        self.assertNotIn("image_warning", page)

    def test_comparison_failure_writes_error_trace_and_failed_state(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])
        self.index_document(sop["document_id"])

        with patch(
            "backend.services.comparison_service.run_document_comparison",
            side_effect=fake_compare_documents_connection_error,
        ):
            response = self.client.post(
                "/comparisons",
                json={
                    "regulatory_document_id": regulatory["document_id"],
                    "sop_document_id": sop["document_id"],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        comparison_id = response.json()["comparison_id"]
        comparison = registry.get_comparison(comparison_id)
        self.assertEqual(comparison["status"], "failed")
        self.assertIn("RuntimeError: Connection error.", comparison["error_message"])
        run_dir = self.storage_root / "comparisons" / comparison_id
        state = json.loads((run_dir / "state" / "comparison_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["current_sop_page"], 4)
        error_trace = (run_dir / "logs" / "error_trace.txt").read_text(encoding="utf-8")
        self.assertIn("RuntimeError: Connection error.", error_trace)
        self.assertIn("sop_page: 4", error_trace)
        self.assertIn("stage: comparison", error_trace)
        self.assertIn("Traceback", error_trace)

    def test_create_comparison_reuses_active_comparison_for_same_pair(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])
        self.index_document(sop["document_id"])
        registry.upsert_comparison(
            {
                "comparison_id": "cmp_000001",
                "regulatory_document_id": regulatory["document_id"],
                "sop_document_id": sop["document_id"],
                "status": "running",
                "created_at": registry.utc_now(),
                "started_at": registry.utc_now(),
                "finished_at": "",
                "report_json_path": "",
                "report_md_path": "",
                "error_message": "",
            }
        )
        registry.upsert_job(
            {
                "job_id": "job_000001",
                "job_type": "compare_documents",
                "document_id": "",
                "comparison_id": "cmp_000001",
                "status": "running",
                "started_at": registry.utc_now(),
                "finished_at": "",
                "error_message": "",
                "log_path": "",
            }
        )

        response = self.client.post(
            "/comparisons",
            json={
                "regulatory_document_id": regulatory["document_id"],
                "sop_document_id": sop["document_id"],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["comparison_id"], "cmp_000001")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(
            [row["comparison_id"] for row in registry.read_comparisons()],
            ["cmp_000001"],
        )

    def test_create_comparison_retries_latest_failed_comparison_for_same_pair(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])
        self.index_document(sop["document_id"])
        run_dir = self.storage_root / "comparisons" / "cmp_000001"
        (run_dir / "state").mkdir(parents=True)
        (run_dir / "state" / "comparison_state.json").write_text(
            json.dumps(
                {
                    "comparison_run_id": "cmp_000001",
                    "last_completed_sop_page": 3,
                    "current_sop_page": 4,
                    "completed_item_result_paths": [],
                    "completed_page_result_paths": [],
                    "status": "failed",
                }
            ),
            encoding="utf-8",
        )
        registry.upsert_comparison(
            {
                "comparison_id": "cmp_000001",
                "regulatory_document_id": regulatory["document_id"],
                "sop_document_id": sop["document_id"],
                "status": "failed",
                "created_at": registry.utc_now(),
                "started_at": registry.utc_now(),
                "finished_at": registry.utc_now(),
                "report_json_path": "",
                "report_md_path": "",
                "error_message": "RuntimeError: Connection error.",
            }
        )

        with patch(
            "backend.services.comparison_service.run_document_comparison",
            side_effect=fake_compare_documents,
        ) as run_comparison:
            response = self.client.post(
                "/comparisons",
                json={
                    "regulatory_document_id": regulatory["document_id"],
                    "sop_document_id": sop["document_id"],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["comparison_id"], "cmp_000001")
        self.assertEqual([row["comparison_id"] for row in registry.read_comparisons()], ["cmp_000001"])
        self.assertEqual(run_comparison.call_args.kwargs["comparison_run_id"], "cmp_000001")
        self.assertEqual(run_comparison.call_args.kwargs["comparison_run_dir"], run_dir)

    def test_get_active_comparison_for_pair_returns_running_comparison(self):
        registry.upsert_comparison(
            {
                "comparison_id": "cmp_000001",
                "regulatory_document_id": "reg_000001",
                "sop_document_id": "sop_000001",
                "status": "running",
                "created_at": "2026-05-22T01:00:00+00:00",
                "started_at": "2026-05-22T01:00:01+00:00",
                "finished_at": "",
                "report_json_path": "",
                "report_md_path": "",
                "error_message": "",
            }
        )

        response = self.client.get(
            "/comparisons/by-pair/active",
            params={
                "regulatory_document_id": "reg_000001",
                "sop_document_id": "sop_000001",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["active_comparison_id"], "cmp_000001")
        self.assertEqual(payload["latest_comparison_id"], "cmp_000001")
        self.assertEqual(payload["status"], "running")
        self.assertNotIn("job_id", payload)

    def test_get_comparison_progress_hides_job_id_and_returns_page_progress(self):
        registry.upsert_comparison(
            {
                "comparison_id": "cmp_000001",
                "regulatory_document_id": "reg_000001",
                "sop_document_id": "sop_000001",
                "status": "running",
                "created_at": registry.utc_now(),
                "started_at": registry.utc_now(),
                "finished_at": "",
                "report_json_path": "",
                "report_md_path": "",
                "error_message": "",
            }
        )
        registry.upsert_job(
            {
                "job_id": "job_000001",
                "job_type": "compare_documents",
                "document_id": "",
                "comparison_id": "cmp_000001",
                "status": "running",
                "started_at": registry.utc_now(),
                "finished_at": "",
                "error_message": "",
                "log_path": "",
            }
        )
        job_event_service.append_event(
            "job_000001",
            stage="comparison",
            step="plan_sop_page",
            message="Planning SOP page 5 of 10.",
            progress_current=5,
            progress_total=10,
        )

        response = self.client.get("/comparisons/cmp_000001/progress")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["comparison_id"], "cmp_000001")
        self.assertEqual(payload["progress_current"], 5)
        self.assertEqual(payload["progress_total"], 10)
        self.assertEqual(payload["progress_percent"], 0.5)
        self.assertEqual(payload["current_step"], "plan_sop_page")
        self.assertFalse(payload["report_ready"])
        self.assertNotIn("job_id", payload)
        self.assertNotIn("job_id", payload["events"][0])

    def test_completed_comparison_progress_reports_full_progress(self):
        report_path = self.storage_root / "comparisons" / "cmp_000001" / "final_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        registry.upsert_comparison(
            {
                "comparison_id": "cmp_000001",
                "regulatory_document_id": "reg_000001",
                "sop_document_id": "sop_000001",
                "status": "completed",
                "created_at": registry.utc_now(),
                "started_at": registry.utc_now(),
                "finished_at": registry.utc_now(),
                "report_json_path": str(report_path),
                "report_md_path": "",
                "error_message": "",
            }
        )
        registry.upsert_job(
            {
                "job_id": "job_000001",
                "job_type": "compare_documents",
                "document_id": "",
                "comparison_id": "cmp_000001",
                "status": "completed",
                "started_at": registry.utc_now(),
                "finished_at": registry.utc_now(),
                "error_message": "",
                "log_path": "",
            }
        )
        job_event_service.append_event(
            "job_000001",
            stage="comparison",
            step="write_page_report",
            message="Completed SOP page 1 of 2.",
            progress_current=1,
            progress_total=2,
        )

        response = self.client.get("/comparisons/cmp_000001/progress")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["message"], "Comparison complete.")
        self.assertEqual(payload["progress_current"], 2)
        self.assertEqual(payload["progress_total"], 2)
        self.assertEqual(payload["progress_percent"], 1.0)
        self.assertTrue(payload["report_ready"])

    def test_get_comparisons_returns_rows_with_filenames_and_report_ready(self):
        regulatory = self.upload_pdf("regulatory", "regulatory.pdf")
        sop = self.upload_pdf("sop", "procedure.pdf")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])
        self.index_document(sop["document_id"])

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
        comparison_id = response.json()["comparison_id"]

        response = self.client.get("/comparisons")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["comparisons"]), 1)
        row = payload["comparisons"][0]
        self.assertEqual(row["comparison_id"], comparison_id)
        self.assertEqual(row["regulatory_filename"], "regulatory.pdf")
        self.assertEqual(row["sop_filename"], "procedure.pdf")
        self.assertEqual(row["status"], "completed")
        self.assertTrue(row["report_ready"])

    def test_completed_comparison_download_endpoints_return_csv_and_bundle(self):
        regulatory = self.upload_pdf("regulatory", "regulatory.pdf")
        sop = self.upload_pdf("sop", "procedure.pdf")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])
        self.index_document(sop["document_id"])

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
        comparison_id = response.json()["comparison_id"]

        csv_response = self.client.get(f"/comparisons/{comparison_id}/downloads/csv")
        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        self.assertIn("text/csv", csv_response.headers["content-type"])
        self.assertIn("comparison_id", csv_response.text)

        bundle_response = self.client.get(
            f"/comparisons/{comparison_id}/downloads/thought-analysis-bundle"
        )
        self.assertEqual(bundle_response.status_code, 200, bundle_response.text)
        self.assertIn("application/json", bundle_response.headers["content-type"])
        bundle = bundle_response.json()
        self.assertEqual(bundle["comparison_id"], comparison_id)
        self.assertEqual(bundle["regulatory_filename"], "regulatory.pdf")
        self.assertEqual(bundle["sop_filename"], "procedure.pdf")
        self.assertIn("status_taxonomy", bundle)
        self.assertIn("page_reports", bundle)
        self.assertIn("final_findings", bundle)
        self.assertIn("job_events", bundle)
        self.assertIn("missing_debug_artifacts", bundle)
        self.assertIn("hidden chain-of-thought is not included", bundle["safety_note"])
        self.assertFalse(has_hidden_chain_of_thought_key(bundle))

    def test_csv_download_regenerates_missing_csv_from_report(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])
        self.index_document(sop["document_id"])

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
        comparison_id = response.json()["comparison_id"]
        csv_path = self.storage_root / "comparisons" / comparison_id / "final_report.csv"
        csv_path.unlink()

        csv_response = self.client.get(f"/comparisons/{comparison_id}/downloads/csv")

        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        self.assertTrue(csv_path.exists())
        header = csv_response.text.splitlines()[0]
        for column in [
            "comparison_id",
            "sop_page",
            "page_status",
            "status",
            "severity",
            "recommended_action",
        ]:
            self.assertIn(column, header)

    def test_download_endpoints_reject_incomplete_comparison(self):
        registry.upsert_comparison(
            {
                "comparison_id": "cmp_000001",
                "regulatory_document_id": "reg_000001",
                "sop_document_id": "sop_000001",
                "status": "running",
                "created_at": registry.utc_now(),
                "started_at": registry.utc_now(),
                "finished_at": "",
                "report_json_path": "",
                "report_md_path": "",
                "error_message": "",
            }
        )

        csv_response = self.client.get("/comparisons/cmp_000001/downloads/csv")
        bundle_response = self.client.get(
            "/comparisons/cmp_000001/downloads/thought-analysis-bundle"
        )

        self.assertEqual(csv_response.status_code, 400)
        self.assertEqual(bundle_response.status_code, 400)
        self.assertIn("not completed", csv_response.text.lower())
        self.assertIn("not completed", bundle_response.text.lower())

    def test_comparison_requires_both_documents_processed_and_indexed(self):
        regulatory = self.upload_pdf("regulatory")
        sop = self.upload_pdf("sop")
        self.process_document(regulatory["document_id"])
        self.process_document(sop["document_id"])
        self.index_document(regulatory["document_id"])

        response = self.client.post(
            "/comparisons",
            json={
                "regulatory_document_id": regulatory["document_id"],
                "sop_document_id": sop["document_id"],
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_job_events_are_written_and_returned(self):
        sop = self.upload_pdf("sop")
        job = self.process_document(sop["document_id"])

        response = self.client.get(f"/jobs/{job['job_id']}/events")

        self.assertEqual(response.status_code, 200)
        events = response.json()["events"]
        self.assertTrue(events)
        self.assertTrue(any(event["step"] == "completed" for event in events))

    def test_copilot_query_uses_selected_document_topic_index(self):
        sop = self.upload_pdf("sop")
        self.process_document(sop["document_id"])
        self.index_document(sop["document_id"])

        with patch(
            "backend.services.copilot_service.run_document_retrieval",
            side_effect=fake_retrieve_document,
        ) as run_retrieval:
            response = self.client.post(
                f"/documents/{sop['document_id']}/copilot/query",
                json={"query": "What evidence is prepared?"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["document_id"], sop["document_id"])
        self.assertEqual(payload["answer"]["answer"], "Co-pilot answer [p. 1].")
        kwargs = run_retrieval.call_args.kwargs
        self.assertTrue(str(kwargs["topic_index_path"]).endswith("indexing_output\\topic_index.json"))
        self.assertTrue(str(kwargs["pages_folder_path"]).endswith("enriched_doc\\pages_md"))

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
