import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import registry
from backend.services.artifact_retention_service import cleanup_document_artifacts


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x00IEND\xaeB`\x82"
)


def write_file(path: Path, content: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.temp_dir.name) / "storage"
        self.env_patch = patch.dict(
            os.environ,
            {"INDEXAI_STORAGE_ROOT": str(self.storage_root)},
        )
        self.env_patch.start()
        registry.ensure_storage()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def create_document_artifacts(self, document_id: str = "doc_000001") -> Path:
        root = self.storage_root / "documents" / document_id
        write_file(root / "original" / "source.pdf", "%PDF-1.4\n")
        manifest = {
            "document_id": document_id,
            "source_file": "original/source.pdf",
            "enriched_pages_folder": "enriched_doc/pages_md",
            "page_images_folder": "docling_assets/page_images",
            "total_pages": 1,
            "topic_index_path": "indexing_output/topic_index.json",
            "agent_md_path": "indexing_output/agent.md",
        }
        write_file(root / "manifest.json", json.dumps(manifest))
        write_file(root / "docling_assets" / "pages_md" / "page_0001.md", "raw")
        (root / "docling_assets" / "page_images").mkdir(parents=True)
        (root / "docling_assets" / "page_images" / "page-1.png").write_bytes(PNG_BYTES)
        write_file(root / "docling_assets" / "image_png_images" / "picture-1.png", "raw-picture")
        write_file(root / "docling_assets" / "table_images" / "table-1.png", "raw-table")
        write_file(root / "docling_assets" / "formula_images" / "formula-1.png", "raw-formula")
        write_file(root / "docling_assets" / "stitched_raw_docling_markdown.md", "stitched")
        write_file(root / "enriched_doc" / "pages_md" / "page_0001.md", "enriched")
        write_file(root / "enriched_doc" / "image_png_images" / "picture-1.png", "enriched-picture")
        write_file(root / "enriched_doc" / "table_images" / "table-1.png", "enriched-table")
        write_file(root / "enriched_doc" / "formula_images" / "formula-1.png", "enriched-formula")
        write_file(root / "enriched_doc" / "readable_processed_doc.md", "readable")
        write_file(root / "indexing_output" / "topic_index.json", "[]")
        write_file(root / "indexing_output" / "agent.md", "# Agent Memory Guide\n")
        write_file(root / "indexing_output" / "processing_state.json", "{}")
        write_file(root / "indexing_output" / "validation_report.json", "{}")
        write_file(root / "indexing_output" / "revision_log.md", "log")
        write_file(root / "indexing_output" / "backups" / "topic_index_before_step_0001.json", "[]")
        registry.upsert_document(
            {
                "document_id": document_id,
                "original_filename": "source.pdf",
                "stored_pdf_path": str(root / "original" / "source.pdf"),
                "asset_root": str(root),
                "uploaded_at": registry.utc_now(),
                "processing_status": "completed",
                "indexing_status": "completed",
                "indexed": "true",
                "page_count": "1",
                "active_job_id": "",
                "error_message": "",
            }
        )
        return root

    def test_standard_document_cleanup_keeps_product_files_and_deletes_raw_duplicates(self):
        root = self.create_document_artifacts()

        with patch("backend.config.ARTIFACT_RETENTION_MODE", "standard"):
            result = cleanup_document_artifacts("doc_000001")

        self.assertEqual(result["mode"], "standard")
        self.assertTrue((root / "original" / "source.pdf").exists())
        self.assertTrue((root / "manifest.json").exists())
        self.assertTrue((root / "page_images" / "page-1.png").exists())
        self.assertTrue((root / "enriched_doc" / "pages_md" / "page_0001.md").exists())
        self.assertTrue((root / "enriched_doc" / "readable_processed_doc.md").exists())
        self.assertTrue((root / "indexing_output" / "topic_index.json").exists())
        self.assertTrue((root / "indexing_output" / "agent.md").exists())
        self.assertFalse((root / "docling_assets").exists())
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["page_images_folder"], "page_images")
        self.assertEqual(manifest["artifact_retention_mode"], "standard")
        self.assertIn("docling_assets/pages_md", manifest["deleted_artifacts"])

    def test_debug_mode_deletes_nothing(self):
        document_root = self.create_document_artifacts()

        with patch("backend.config.ARTIFACT_RETENTION_MODE", "debug"):
            cleanup_document_artifacts("doc_000001")

        self.assertTrue((document_root / "docling_assets" / "pages_md" / "page_0001.md").exists())
        self.assertTrue((document_root / "docling_assets" / "page_images" / "page-1.png").exists())

    def test_minimal_document_cleanup_removes_indexing_debug_files_but_keeps_topic_index(self):
        root = self.create_document_artifacts()

        with patch("backend.config.ARTIFACT_RETENTION_MODE", "minimal"):
            cleanup_document_artifacts("doc_000001")

        self.assertTrue((root / "indexing_output" / "topic_index.json").exists())
        self.assertTrue((root / "indexing_output" / "agent.md").exists())
        self.assertFalse((root / "indexing_output" / "processing_state.json").exists())
        self.assertFalse((root / "indexing_output" / "validation_report.json").exists())
        self.assertFalse((root / "indexing_output" / "revision_log.md").exists())
        self.assertFalse((root / "indexing_output" / "backups").exists())


if __name__ == "__main__":
    unittest.main()
