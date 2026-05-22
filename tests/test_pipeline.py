import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from doc_processing.pipeline import run_document_processing


class PipelineTests(unittest.TestCase):
    def test_run_document_processing_does_not_start_document_indexing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            asset_root = Path(temp_dir) / "sample_doc_assets"
            docling_assets_dir = asset_root / "docling_assets"
            pages_md_dir = docling_assets_dir / "pages_md"
            enriched_pages_dir = asset_root / "enriched_doc" / "pages_md"

            docling_output = SimpleNamespace(
                docling_assets_dir=docling_assets_dir,
                pages_md_dir=pages_md_dir,
            )
            enriched_output = SimpleNamespace(
                pages_md_dir=enriched_pages_dir,
                readable_markdown_file=asset_root
                / "enriched_doc"
                / "readable_processed_doc.md",
            )

            with patch(
                "doc_processing.pipeline.convert_pdf_with_docling",
                return_value=docling_output,
            ), patch(
                "doc_processing.pipeline.detect_table_continuity",
                return_value={"multi_page_table_count": 0},
            ), patch(
                "doc_processing.pipeline.enrich_document",
                return_value=enriched_output,
            ), patch(
                "document_indexing.run_document_indexing"
            ) as run_document_indexing:
                run_document_processing(pdf_path)

            run_document_indexing.assert_not_called()

    def test_run_document_processing_accepts_explicit_output_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            output_root = Path(temp_dir) / "storage" / "documents" / "sop" / "sop_000001"
            docling_assets_dir = output_root / "docling_assets"
            pages_md_dir = docling_assets_dir / "pages_md"
            enriched_doc_dir = output_root / "enriched_doc"
            enriched_pages_dir = enriched_doc_dir / "pages_md"

            docling_output = SimpleNamespace(
                docling_assets_dir=docling_assets_dir,
                pages_md_dir=pages_md_dir,
            )
            enriched_output = SimpleNamespace(
                pages_md_dir=enriched_pages_dir,
                readable_markdown_file=enriched_doc_dir / "readable_processed_doc.md",
            )

            with patch(
                "doc_processing.pipeline.convert_pdf_with_docling",
                return_value=docling_output,
            ) as convert_pdf, patch(
                "doc_processing.pipeline.detect_table_continuity",
                return_value={"multi_page_table_count": 0},
            ), patch(
                "doc_processing.pipeline.enrich_document",
                return_value=enriched_output,
            ) as enrich_document:
                run_document_processing(pdf_path, output_root=output_root)

            convert_pdf.assert_called_once_with(
                pdf_path,
                output_root=output_root,
                event_callback=None,
            )
            enrich_document.assert_called_once_with(
                docling_assets_dir,
                output_root=enriched_doc_dir,
            )

    def test_run_document_processing_passes_event_callback_and_emits_final_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            asset_root = Path(temp_dir) / "sample_doc_assets"
            docling_assets_dir = asset_root / "docling_assets"
            pages_md_dir = docling_assets_dir / "pages_md"
            enriched_pages_dir = asset_root / "enriched_doc" / "pages_md"
            enriched_pages_dir.mkdir(parents=True)
            (enriched_pages_dir / "page_0001.md").write_text("page", encoding="utf-8")
            events = []

            docling_output = SimpleNamespace(
                docling_assets_dir=docling_assets_dir,
                pages_md_dir=pages_md_dir,
            )
            enriched_output = SimpleNamespace(
                pages_md_dir=enriched_pages_dir,
                readable_markdown_file=asset_root
                / "enriched_doc"
                / "readable_processed_doc.md",
            )
            callback = lambda *args: events.append(args)

            with patch(
                "doc_processing.pipeline.convert_pdf_with_docling",
                return_value=docling_output,
            ) as convert_pdf, patch(
                "doc_processing.pipeline.detect_table_continuity",
                return_value={"multi_page_table_count": 0},
            ), patch(
                "doc_processing.pipeline.enrich_document",
                return_value=enriched_output,
            ):
                run_document_processing(pdf_path, event_callback=callback)

            self.assertIs(convert_pdf.call_args.kwargs["event_callback"], callback)
            self.assertIn(
                ("document_processing", "processing_page", "Processing page 1 of 1", 1, 1),
                events,
            )


if __name__ == "__main__":
    unittest.main()
