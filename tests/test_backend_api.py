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
from backend.services import registry
from document_retrieval.schemas import FinalAnswer, RetrievalOutput, RetrievalTrace


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x00IEND\xaeB`\x82"
)


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


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
    (images / "page-1.png").write_bytes(PNG_BYTES)
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
                    "description": "Evidence for prepared controls.",
                    "assets": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    (output_folder / "processing_state.json").write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        topic_index_path=topic_index_path,
        processing_state_path=output_folder / "processing_state.json",
        revision_log_path=output_folder / "revision_log.md",
        validation_report_path=output_folder / "validation_report.json",
        agent_md_path=output_folder / "agent.md",
    )


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
            {"INDEXAI_STORAGE_ROOT": str(self.storage_root)},
        )
        self.env_patch.start()
        self.client = TestClient(create_app())

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def upload_pdf(self, filename: str = "source.pdf") -> dict:
        response = self.client.post(
            "/documents/upload",
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

    def test_app_title_routes_and_health_reflect_indexai_surface(self):
        app = create_app()
        self.assertEqual(app.title, "IndexAI")
        paths = {route.path for route in app.routes}
        self.assertIn("/documents/upload", paths)
        self.assertIn("/documents/{document_id}/copilot/query", paths)
        self.assertIn("/jobs/{job_id}", paths)
        self.assertIn("/assets/documents/{document_id}/page-image/{page_number}", paths)
        self.assertNotIn("/comparisons", paths)

        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/comparisons").status_code, 404)

    def test_upload_document_creates_single_document_storage_and_response(self):
        document = self.upload_pdf("handbook.pdf")

        self.assertEqual(document["document_id"], "doc_000001")
        self.assertEqual(document["filename"], "handbook.pdf")
        self.assertFalse(document["indexed"])
        self.assertNotIn("memory_ready", document)
        self.assertNotIn("ready_for_" + "comparison", document)
        self.assertNotIn("document_type", document)

        root = self.storage_root / "documents" / "doc_000001"
        self.assertTrue((root / "original" / "source.pdf").exists())
        rows = read_csv_rows(self.storage_root / "registries" / "document_registry.csv")
        self.assertNotIn("document_type", rows[0])
        self.assertNotIn("ready_for_" + "comparison", rows[0])
        self.assertEqual(rows[0]["indexed"], "false")
        self.assertEqual(rows[0]["indexing_status"], "not_started")

    def test_upload_rejects_non_pdf(self):
        response = self.client.post(
            "/documents/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)

    def test_process_and_index_document_make_indexed_memory_ready(self):
        document = self.upload_pdf()

        process_job = self.process_document(document["document_id"])
        self.assertEqual(process_job["status"], "queued")
        self.assertNotIn("comparison" + "_id", process_job)
        processed = self.client.get("/documents").json()["documents"][0]
        self.assertFalse(processed["indexed"])
        self.assertEqual(processed["indexing_status"], "not_started")

        index_job = self.index_document(document["document_id"])
        self.assertEqual(index_job["job_type"], "index_document")
        indexed = self.client.get("/documents").json()["documents"][0]
        self.assertTrue(indexed["indexed"])
        self.assertEqual(indexed["processing_status"], "completed")
        self.assertEqual(indexed["indexing_status"], "completed")

        manifest_path = self.storage_root / "documents" / document["document_id"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("document_type", manifest)
        self.assertEqual(manifest["topic_index_path"], "indexing_output/topic_index.json")
        self.assertEqual(manifest["agent_md_path"], "indexing_output/agent.md")
        agent_md_path = (
            self.storage_root
            / "documents"
            / document["document_id"]
            / "indexing_output"
            / "agent.md"
        )
        self.assertTrue(agent_md_path.exists())
        agent_md = agent_md_path.read_text(encoding="utf-8")
        self.assertIn("Read `indexing_output/topic_index.json` first.", agent_md)
        self.assertIn("Do not read the whole document by default.", agent_md)
        self.assertIn("- filename: source.pdf", agent_md)
        self.assertIn("- page images folder: `page_images`", agent_md)
        self.assertIn(
            "- Prepared evidence controls | pages 1 | Evidence for prepared controls.",
            agent_md,
        )

        events = self.client.get(f"/jobs/{index_job['job_id']}/events").json()["events"]
        self.assertNotIn(
            "comparison",
            " ".join(event["message"].lower() for event in events),
        )

    def test_processing_writes_single_document_manifest(self):
        document = self.upload_pdf("handbook.pdf")

        self.process_document(document["document_id"])

        manifest_path = self.storage_root / "documents" / document["document_id"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest,
            {
                "document_id": document["document_id"],
                "source_file": "original/source.pdf",
                "enriched_pages_folder": "enriched_doc/pages_md",
                "page_images_folder": "docling_assets/page_images",
                "total_pages": 1,
            },
        )

    def test_rerunning_indexing_refreshes_agent_memory_guide(self):
        document = self.upload_pdf()
        self.process_document(document["document_id"])
        self.index_document(document["document_id"])
        agent_md_path = (
            self.storage_root
            / "documents"
            / document["document_id"]
            / "indexing_output"
            / "agent.md"
        )
        agent_md_path.write_text("stale guide", encoding="utf-8")

        self.index_document(document["document_id"])

        agent_md = agent_md_path.read_text(encoding="utf-8")
        self.assertNotEqual(agent_md, "stale guide")
        self.assertIn("Read `indexing_output/topic_index.json` first.", agent_md)
        self.assertIn("- agent guide: `indexing_output/agent.md`", agent_md)

    def test_prepare_endpoint_runs_processing_then_indexing(self):
        document = self.upload_pdf()
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
            response = self.client.post(f"/documents/{document['document_id']}/prepare")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls, ["process", "index"])
        prepared = self.client.get("/documents").json()["documents"][0]
        self.assertTrue(prepared["indexed"])

    def test_job_events_are_written_and_returned(self):
        document = self.upload_pdf()
        job = self.process_document(document["document_id"])

        response = self.client.get(f"/jobs/{job['job_id']}/events")

        self.assertEqual(response.status_code, 200)
        events = response.json()["events"]
        self.assertTrue(events)
        self.assertTrue(any(event["step"] == "completed" for event in events))

    def test_copilot_query_uses_selected_document_topic_index(self):
        document = self.upload_pdf()
        self.process_document(document["document_id"])
        self.index_document(document["document_id"])

        with patch(
            "backend.services.copilot_service.run_document_retrieval",
            side_effect=fake_retrieve_document,
        ) as run_retrieval:
            response = self.client.post(
                f"/documents/{document['document_id']}/copilot/query",
                json={"query": "What evidence is prepared?"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["document_id"], document["document_id"])
        self.assertEqual(payload["answer"]["answer"], "Co-pilot answer [p. 1].")
        kwargs = run_retrieval.call_args.kwargs
        self.assertTrue(str(kwargs["topic_index_path"]).endswith("indexing_output\\topic_index.json"))
        self.assertTrue(str(kwargs["pages_folder_path"]).endswith("enriched_doc\\pages_md"))

    def test_copilot_rejects_unindexed_document(self):
        document = self.upload_pdf()

        response = self.client.post(
            f"/documents/{document['document_id']}/copilot/query",
            json={"query": "What evidence is prepared?"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("processed and indexed", response.json()["detail"])

    def test_asset_endpoint_returns_page_image_or_404(self):
        document = self.upload_pdf()
        self.process_document(document["document_id"])

        found = self.client.get(f"/assets/documents/{document['document_id']}/page-image/1")
        missing = self.client.get(f"/assets/documents/{document['document_id']}/page-image/99")

        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.headers["content-type"], "image/png")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
