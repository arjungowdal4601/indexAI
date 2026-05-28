import json
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeHttpResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeBytesResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


class FrontendApiClientTests(unittest.TestCase):
    def test_list_documents_uses_configured_base_url_and_type_filter(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["timeout"] = timeout
            return FakeHttpResponse({"documents": []})

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.list_documents("regulatory")

        self.assertEqual(result, {"documents": []})
        self.assertEqual(
            captured,
            {
                "url": "http://api.local/documents?document_type=regulatory",
                "method": "GET",
                "timeout": 30,
            },
        )

    def test_create_comparison_posts_selected_document_ids(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {"comparison_id": "cmp_000001", "job_id": "job_000001", "status": "queued"}
            )

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local/"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.create_comparison("reg_000001", "sop_000001")

        self.assertEqual(result["comparison_id"], "cmp_000001")
        self.assertEqual(captured["url"], "http://api.local/comparisons")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["body"],
            {
                "regulatory_document_id": "reg_000001",
                "sop_document_id": "sop_000001",
            },
        )

    def test_get_job_events_uses_job_events_endpoint(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            return FakeHttpResponse({"job_id": "job_000001", "events": []})

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.get_job_events("job_000001")

        self.assertEqual(result["events"], [])
        self.assertEqual(captured["url"], "http://api.local/jobs/job_000001/events")
        self.assertEqual(captured["method"], "GET")

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
                    "document_id": "sop_000001",
                    "comparison_id": None,
                    "started_at": None,
                    "finished_at": None,
                    "error_message": None,
                }
            )

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.start_prepare("sop_000001")

        self.assertEqual(result["job_type"], "prepare_document")
        self.assertEqual(captured["url"], "http://api.local/documents/sop_000001/prepare")
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
                    "document_id": "sop_000001",
                    "answer": {},
                    "retrieval_trace": {},
                    "selected_pages": [],
                }
            )

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.copilot_query("sop_000001", "What does this document require?")

        self.assertEqual(result["document_id"], "sop_000001")
        self.assertEqual(captured["url"], "http://api.local/documents/sop_000001/copilot/query")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["body"],
            {
                "query": "What does this document require?",
                "max_direct_pages": 10,
                "max_direct_estimated_tokens": 70000,
            },
        )

    def test_get_active_comparison_for_pair_calls_backend_endpoint(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            return FakeHttpResponse(
                {
                    "regulatory_document_id": "reg_000001",
                    "sop_document_id": "sop_000001",
                    "active_comparison_id": "cmp_000001",
                    "latest_comparison_id": "cmp_000001",
                    "status": "running",
                    "message": "Active comparison is running.",
                }
            )

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.get_active_comparison_for_pair("reg_000001", "sop_000001")

        self.assertEqual(result["active_comparison_id"], "cmp_000001")
        self.assertEqual(
            captured["url"],
            "http://api.local/comparisons/by-pair/active?"
            "regulatory_document_id=reg_000001&sop_document_id=sop_000001",
        )
        self.assertEqual(captured["method"], "GET")

    def test_get_comparison_progress_calls_progress_endpoint(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            return FakeHttpResponse(
                {
                    "comparison_id": "cmp_000001",
                    "status": "running",
                    "progress_current": 3,
                    "progress_total": 15,
                    "progress_percent": 0.2,
                    "events": [],
                }
            )

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.get_comparison_progress("cmp_000001")

        self.assertEqual(result["progress_current"], 3)
        self.assertEqual(captured["url"], "http://api.local/comparisons/cmp_000001/progress")
        self.assertEqual(captured["method"], "GET")

    def test_list_comparisons_calls_comparisons_endpoint(self):
        from frontend import api_client

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            return FakeHttpResponse({"comparisons": []})

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            result = api_client.list_comparisons()

        self.assertEqual(result, {"comparisons": []})
        self.assertEqual(captured["url"], "http://api.local/comparisons")
        self.assertEqual(captured["method"], "GET")

    def test_report_download_helpers_call_download_endpoints(self):
        from frontend import api_client

        captured = []

        def fake_urlopen(request, timeout):
            captured.append(
                {
                    "url": request.full_url,
                    "method": request.get_method(),
                    "timeout": timeout,
                    "accept": request.headers.get("Accept"),
                }
            )
            return FakeBytesResponse(b"download-bytes")

        with patch.dict(
            os.environ,
            {"DOC_COMPARING_API_BASE_URL": "http://api.local"},
        ), patch("frontend.api_client.urlopen", side_effect=fake_urlopen):
            csv_payload = api_client.download_comparison_csv("cmp_000001")
            bundle_payload = api_client.download_thought_analysis_bundle("cmp_000001")

        self.assertEqual(csv_payload, b"download-bytes")
        self.assertEqual(bundle_payload, b"download-bytes")
        self.assertEqual(
            [item["url"] for item in captured],
            [
                "http://api.local/comparisons/cmp_000001/downloads/csv",
                "http://api.local/comparisons/cmp_000001/downloads/thought-analysis-bundle",
            ],
        )
        self.assertEqual([item["method"] for item in captured], ["GET", "GET"])


class FrontendContractTests(unittest.TestCase):
    def _load_review_report_module(self):
        path = Path("frontend/pages/3_Review_Report.py")
        spec = importlib.util.spec_from_file_location("review_report_page", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_streamlit_frontend_files_exist(self):
        expected = [
            "frontend/streamlit_app.py",
            "frontend/api_client.py",
            "frontend/ui_components.py",
            "frontend/pages/1_Upload_and_Prepare.py",
            "frontend/pages/2_Compare_Documents.py",
            "frontend/pages/3_Review_Report.py",
            "frontend/pages/4_Document_Copilot.py",
        ]

        for path in expected:
            self.assertTrue(Path(path).exists(), path)

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
            "from document_comparison",
            "import document_comparison",
        ]
        for forbidden in forbidden_imports:
            self.assertNotIn(forbidden, combined)
        self.assertIn("api_client", combined)
        self.assertIn("/assets/documents/", combined)

    def test_upload_prepare_page_uses_prepare_not_process_or_index(self):
        source = Path("frontend/pages/1_Upload_and_Prepare.py").read_text(encoding="utf-8")

        self.assertIn("start_prepare", source)
        self.assertNotIn("start_processing", source)
        self.assertNotIn("start_indexing", source)
        self.assertNotIn("Job Status", source)

    def test_compare_page_hides_job_id_and_polls_by_comparison_id(self):
        source = Path("frontend/pages/2_Compare_Documents.py").read_text(encoding="utf-8")

        self.assertIn("render_comparison_progress", source)
        self.assertIn("get_active_comparison_for_pair", source)
        self.assertIn("st.dataframe", source)
        self.assertIn("selected_regulatory_document_id", source)
        self.assertIn("selected_sop_document_id", source)
        self.assertIn("Document ID", source)
        self.assertIn("Filename", source)
        self.assertNotIn("render_job_monitor", source)
        self.assertNotIn("last_job_id", source)
        self.assertNotIn("Job ID", source)
        self.assertNotIn("st.text_input", source)

    def test_review_report_uses_comparison_browser_not_manual_id_input(self):
        source = Path("frontend/pages/3_Review_Report.py").read_text(encoding="utf-8")

        self.assertIn("Comparison Reports", source)
        self.assertIn("list_comparisons", source)
        self.assertIn("selected_comparison_id", source)
        self.assertIn("View", source)
        self.assertNotIn("st.text_input", source)

    def test_review_report_uses_simplified_reviewer_controls(self):
        source = Path("frontend/pages/3_Review_Report.py").read_text(encoding="utf-8")

        self.assertIn("inject_review_report_styles", source)
        self.assertIn("_render_review_header", source)
        self.assertIn("_render_status_guide", source)
        self.assertIn("_render_status_filters", source)
        self.assertIn("_render_page_navigation", source)
        self.assertIn("_status_badge_html", source)
        self.assertIn("_render_image_panel", source)
        self.assertIn("_render_analysis_panel", source)
        self.assertIn("_render_finding_card", source)
        self.assertIn("st.columns([5, 7]", source)
        self.assertIn("vertical_alignment=\"top\"", source)
        self.assertIn("gap=\"large\"", source)
        self.assertIn("container(border=True)", source)
        self.assertIn("Status guide", source)
        self.assertIn("Filter by status", source)
        self.assertIn("Compliant — SOP covers the requirement.", source)
        self.assertIn("Partial — SOP covers it, but some controls/evidence are missing.", source)
        self.assertIn("Missing — SOP does not cover the requirement.", source)
        self.assertIn(
            "Conflicting — SOP says something that conflicts with the regulatory expectation.",
            source,
        )
        self.assertIn("Needs review — evidence is unclear; human reviewer should decide.", source)
        self.assertIn(
            "Not applicable — page/content is not relevant to GMP comparison.",
            source,
        )
        self.assertIn("st.checkbox", source)
        self.assertIn("st.number_input", source)
        self.assertIn("selected_sop_page_", source)
        self.assertIn("Previous", source)
        self.assertIn("Next", source)
        self.assertIn("No findings match the selected status filter on this page.", source)
        self.assertIn("Download CSV report", source)
        self.assertIn("Download Thought Analysis Bundle", source)
        self.assertIn("download_comparison_csv", source)
        self.assertIn("download_thought_analysis_bundle", source)
        self.assertNotIn("Page range", source)
        self.assertNotIn("Jump to page", source)
        self.assertNotIn("st.slider", source)
        self.assertNotIn("st.selectbox", source)
        self.assertNotIn("Severity filter", source)
        self.assertNotIn("Human-review only", source)
        self.assertNotIn("selected_severity", source)
        self.assertNotIn("human_only", source)
        self.assertNotIn("st.json(summary)", source)
        self.assertNotIn("render_status(", source)
        self.assertNotIn("Download report JSON", source)
        self.assertNotIn("Download report Markdown", source)
        self.assertNotIn("_report_markdown", source)

    def test_review_report_status_helpers_render_readable_labels(self):
        review_report = self._load_review_report_module()

        self.assertEqual(review_report._status_label("partially_compliant"), "Partial")
        self.assertEqual(review_report._status_label("major_gaps"), "Missing")
        self.assertEqual(review_report._status_label("needs_human_review"), "Needs review")
        badge = review_report._status_badge_html("partially_compliant")
        self.assertIn("Partial", badge)
        self.assertNotIn("partially_compliant", badge)

    def test_review_report_navigation_does_not_mutate_widget_key_after_input(self):
        source = Path("frontend/pages/3_Review_Report.py").read_text(encoding="utf-8")
        function_source = source.split("def _render_page_navigation", 1)[1].split(
            "def _filter_page_findings",
            1,
        )[0]
        after_input = function_source.split("st.number_input", 1)[1]

        self.assertNotIn("st.session_state[state_key] =", after_input)

    def test_comparison_progress_uses_status_container_without_job_id(self):
        source = Path("frontend/ui_components.py").read_text(encoding="utf-8")
        function_source = source.split("def render_comparison_progress", 1)[1].split(
            "def render_job_monitor",
            1,
        )[0]

        self.assertIn("st.status", function_source)
        self.assertIn("Comparison running", function_source)
        self.assertIn("get_comparison_progress", function_source)
        self.assertIn("waiting_for_llm", function_source)
        self.assertIn("retry", function_source)
        self.assertIn("failed", function_source)
        self.assertIn("Show comparison steps", function_source)
        self.assertNotIn("job_id", function_source)

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
