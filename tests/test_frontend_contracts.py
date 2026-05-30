import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeHttpResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FrontendApiClientTests(unittest.TestCase):
    def test_list_documents_uses_indexai_base_url(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["timeout"] = timeout
            return FakeHttpResponse({"documents": []})

        with patch.dict(
            os.environ,
            {"INDEXAI_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.list_documents()

        self.assertEqual(result, {"documents": []})
        self.assertEqual(
            captured,
            {
                "url": "http://api.local/documents",
                "method": "GET",
                "timeout": 30,
            },
        )

    def test_doc_comparing_base_url_is_only_migration_fallback(self):
        from frontend import api_client

        with patch.dict(
            os.environ,
            {
                "DOC_COMPARING_API_BASE_URL": "http://legacy.local",
            },
            clear=True,
        ):
            self.assertEqual(api_client.get_api_base_url(), "http://legacy.local")

        with patch.dict(
            os.environ,
            {
                "INDEXAI_API_BASE_URL": "http://api.local",
                "DOC_COMPARING_API_BASE_URL": "http://legacy.local",
            },
            clear=True,
        ):
            self.assertEqual(api_client.get_api_base_url(), "http://api.local")

    def test_start_prepare_calls_prepare_endpoint(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["timeout"] = timeout
            return FakeHttpResponse(
                {
                    "job_id": "job_000001",
                    "job_type": "prepare_document",
                    "status": "queued",
                    "document_id": "doc_000001",
                    "started_at": None,
                    "finished_at": None,
                    "error_message": None,
                }
            )

        with patch.dict(
            os.environ,
            {"INDEXAI_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.start_prepare("doc_000001")

        self.assertEqual(result["job_type"], "prepare_document")
        self.assertEqual(captured["url"], "http://api.local/documents/doc_000001/prepare")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["timeout"], 30)

    def test_copilot_query_posts_selected_document_query(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {
                    "document_id": "doc_000001",
                    "answer": {},
                    "retrieval_trace": {},
                    "selected_pages": [],
                }
            )

        with patch.dict(
            os.environ,
            {"INDEXAI_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.copilot_query("doc_000001", "What does this document say?")

        self.assertEqual(result["document_id"], "doc_000001")
        self.assertEqual(captured["url"], "http://api.local/documents/doc_000001/copilot/query")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["body"],
            {
                "query": "What does this document say?",
                "max_direct_pages": 10,
                "max_direct_estimated_tokens": 70000,
            },
        )

    def test_upload_document_posts_pdf_without_document_type(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = request.data.decode("utf-8", errors="ignore")
            captured["content_type"] = request.headers["Content-type"]
            return FakeHttpResponse({"document_id": "doc_000001"})

        with patch.dict(
            os.environ,
            {"INDEXAI_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.upload_document("handbook.pdf", b"%PDF-1.4\n")

        self.assertEqual(result["document_id"], "doc_000001")
        self.assertEqual(captured["url"], "http://api.local/documents/upload")
        self.assertIn("multipart/form-data", captured["content_type"])
        self.assertIn('name="file"; filename="handbook.pdf"', captured["body"])
        self.assertNotIn("document_type", captured["body"])

    def test_comparison_client_helpers_are_not_exposed(self):
        from frontend import api_client

        removed_helpers = [
            "create_" + "comparison",
            "list_" + "comparisons",
            "get_" + "comparison",
            "get_active_" + "comparison_for_pair",
            "get_" + "comparison_progress",
            "get_" + "comparison_report",
            "download_" + "comparison_csv",
            "download_thought_analysis_" + "bundle",
            "get_page_report",
        ]
        for helper in removed_helpers:
            self.assertFalse(hasattr(api_client, helper), helper)


class FrontendContractTests(unittest.TestCase):
    def test_streamlit_frontend_files_match_indexai_navigation(self):
        expected = [
            "frontend/streamlit_app.py",
            "frontend/api_client.py",
            "frontend/ui_components.py",
            "frontend/pages/1_Upload_and_Index.py",
            "frontend/pages/4_Copilot.py",
        ]
        removed = [
            "frontend/pages/2_Compare_Documents.py",
            "frontend/pages/3_Review_Report.py",
            "frontend/pages/1_Upload_and_Prepare.py",
            "frontend/pages/4_Document_Copilot.py",
        ]

        for path in expected:
            self.assertTrue(Path(path).exists(), path)
        for path in removed:
            self.assertFalse(Path(path).exists(), path)

    def test_frontend_copy_uses_indexai_single_document_language(self):
        frontend_files = [
            path
            for path in Path("frontend").rglob("*.py")
            if "__pycache__" not in path.parts
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in frontend_files)

        self.assertIn("IndexAI", Path("frontend/streamlit_app.py").read_text(encoding="utf-8"))
        self.assertIn("Document Co-pilot", combined)
        for forbidden in [
            "regulat" + "ory",
            "SO" + "P",
            "comparison",
            "gap analysis",
            "review report",
            "thought analysis " + "bundle",
            "Thought Analysis " + "Bundle",
        ]:
            self.assertNotIn(forbidden, combined)

    def test_frontend_calls_backend_not_pipeline_packages(self):
        frontend_files = [
            path
            for path in Path("frontend").rglob("*.py")
            if "__pycache__" not in path.parts
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in frontend_files)

        forbidden_imports = [
            "from doc_processing",
            "import doc_processing",
            "from document_indexing",
            "import document_indexing",
            "from document_" + "comparison",
            "import document_" + "comparison",
        ]
        for forbidden in forbidden_imports:
            self.assertNotIn(forbidden, combined)
        self.assertIn("api_client", combined)
        self.assertIn("/assets/documents/", combined)

    def test_upload_prepare_page_uses_single_prepare_flow(self):
        source = Path("frontend/pages/1_Upload_and_Index.py").read_text(encoding="utf-8")

        self.assertIn("start_prepare", source)
        self.assertIn("upload_document", source)
        self.assertNotIn("start_processing", source)
        self.assertNotIn("start_indexing", source)
        self.assertNotIn("document_type", source)
        self.assertIn('configure_page("Upload and Index")', source)
        self.assertIn('"Index"', source)
        self.assertIn('"Retry Index"', source)
        self.assertIn('"Indexed"', source)

    def test_document_table_uses_indexed_columns_only(self):
        from frontend.ui_components import document_table

        rows = document_table(
            [
                {
                    "document_id": "doc_000001",
                    "filename": "handbook.pdf",
                    "processing_status": "completed",
                    "indexing_status": "completed",
                    "indexed": True,
                    "page_count": 4,
                    "active_job_id": "job_000001",
                    "error_message": "",
                }
            ]
        )

        self.assertEqual(
            list(rows[0].keys()),
            [
                "document_id",
                "filename",
                "processing_status",
                "indexing_status",
                "indexed",
                "page_count",
                "active_job_id",
                "error_message",
            ],
        )

    def test_copilot_page_uses_chat_ui_without_retrieval_controls(self):
        source = Path("frontend/pages/4_Copilot.py").read_text(encoding="utf-8")

        self.assertIn('configure_page("IndexAI Co-pilot")', source)
        self.assertIn("st.chat_message", source)
        self.assertIn("st.chat_input", source)
        self.assertIn("copilot_messages", source)
        self.assertIn("selected_copilot_document_id", source)
        self.assertIn("select any indexed document", source.lower())
        self.assertNotIn("st.tabs", source)
        self.assertNotIn("st.number_input", source)
        self.assertNotIn("Max direct pages", source)
        self.assertNotIn("Max direct estimated tokens", source)
        self.assertNotIn("Retrieval trace", source)
        self.assertNotIn("Memory mode", source)
        self.assertNotIn("Debug", source)
        self.assertNotIn("thought-analysis " + "bundle", source.lower())

    def test_copilot_page_uses_internal_defaults_and_markdown_answer(self):
        source = Path("frontend/pages/4_Copilot.py").read_text(encoding="utf-8")

        self.assertIn("max_direct_pages=5", source)
        self.assertIn("max_direct_estimated_tokens=70000", source)
        self.assertIn("st.markdown", source)
        self.assertIn("I could not find a grounded answer in the selected document.", source)
        self.assertIn("result.get(\"selected_pages\")", source)

    def test_copilot_sources_are_compact_with_images_in_expander(self):
        source = Path("frontend/pages/4_Copilot.py").read_text(encoding="utf-8")

        self.assertIn("Sources:", source)
        self.assertIn("p.{page}", source)
        self.assertIn('st.expander("Show source page images", expanded=False)', source)
        self.assertIn("api_client.page_image_path", source)
        self.assertIn("st.image", source)

    def test_latest_progress_splits_processing_and_indexing_events(self):
        from frontend.ui_components import latest_progress

        events = [
            {
                "stage": "document_processing",
                "progress_current": 2,
                "progress_total": 5,
            },
            {
                "stage": "document_indexing",
                "progress_current": 1,
                "progress_total": 5,
            },
            {
                "stage": "document_processing",
                "progress_current": 4,
                "progress_total": 5,
            },
        ]

        self.assertEqual(latest_progress(events, "document_processing"), (4, 5))
        self.assertEqual(latest_progress(events, "document_indexing"), (1, 5))
        self.assertEqual(
            latest_progress(events, "document_indexing", phase_completed=True),
            (5, 5),
        )


if __name__ == "__main__":
    unittest.main()
