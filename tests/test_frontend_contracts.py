import json
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


class FrontendContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
