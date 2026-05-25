import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from doc_processing.docling_converter import convert_pdf_with_docling


class FakeDoc:
    def __init__(self, page_no):
        self.page_no = page_no
        self.pages = {page_no: SimpleNamespace(image=None)}

    def export_to_markdown(self, **_kwargs):
        return f"# Page {self.page_no}\n\nRaw markdown for page {self.page_no}."

    def iterate_items(self):
        return iter(())


class FakeConverter:
    def __init__(self):
        self.page_ranges = []

    def convert(self, _pdf_path, page_range):
        self.page_ranges.append(page_range)
        return SimpleNamespace(document=FakeDoc(page_range[0]))


class DoclingConverterContractTests(unittest.TestCase):
    def test_recreates_outputs_and_returns_small_output_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            stale_assets = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            stale_pages = stale_assets / "pages_md"
            stale_pages.mkdir(parents=True)
            (stale_pages / "page_9999.md").write_text("stale", encoding="utf-8")
            (stale_assets / "docling_asset_manifest.json").write_text(
                "stale manifest",
                encoding="utf-8",
            )

            fake_converter = FakeConverter()
            with patch(
                "doc_processing.docling_converter.build_docling_converter",
                return_value=fake_converter,
            ):
                output = convert_pdf_with_docling(pdf_path, page_range=(1, 2))

            self.assertEqual(fake_converter.page_ranges, [(1, 1), (2, 2)])
            self.assertTrue(hasattr(output, "docling_assets_dir"))
            self.assertTrue(hasattr(output, "pages_md_dir"))
            self.assertTrue(hasattr(output, "stitched_markdown_file"))

            self.assertEqual(
                output.docling_assets_dir,
                Path(temp_dir) / "sample_doc_assets" / "docling_assets",
            )
            self.assertEqual(output.pages_md_dir, output.docling_assets_dir / "pages_md")
            self.assertEqual(
                output.stitched_markdown_file,
                output.docling_assets_dir / "stitched_raw_docling_markdown.md",
            )

            self.assertFalse((output.pages_md_dir / "page_9999.md").exists())
            self.assertFalse(
                (output.docling_assets_dir / "docling_asset_manifest.json").exists()
            )
            self.assertTrue((output.pages_md_dir / "page_0001.md").exists())
            self.assertTrue((output.pages_md_dir / "page_0002.md").exists())
            self.assertIn(
                "--- PAGE 1 ---",
                (output.pages_md_dir / "page_0001.md").read_text(encoding="utf-8"),
            )
            stitched = output.stitched_markdown_file.read_text(encoding="utf-8")
            self.assertIn("--- PAGE 1 ---", stitched)
            self.assertIn("--- PAGE 2 ---", stitched)

            self.assertTrue(output.page_images_dir.exists())
            self.assertTrue(output.picture_images_dir.exists())
            self.assertTrue(output.table_images_dir.exists())
            self.assertTrue(output.formula_images_dir.exists())

    def test_resume_keeps_existing_page_outputs_and_skips_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            asset_root = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = asset_root / "pages_md"
            page_images_dir = asset_root / "page_images"
            pages_dir.mkdir(parents=True)
            page_images_dir.mkdir(parents=True)
            (pages_dir / "page_0001.md").write_text("--- PAGE 1 ---\nexisting", encoding="utf-8")
            (page_images_dir / "page-1.png").write_bytes(b"image")

            fake_converter = FakeConverter()
            with patch(
                "doc_processing.docling_converter.build_docling_converter",
                return_value=fake_converter,
            ):
                output = convert_pdf_with_docling(
                    pdf_path,
                    page_range=(1, 1),
                    resume=True,
                )

            self.assertEqual(fake_converter.page_ranges, [])
            self.assertEqual(
                (output.pages_md_dir / "page_0001.md").read_text(encoding="utf-8"),
                "--- PAGE 1 ---\nexisting",
            )
            self.assertIn(
                "existing",
                output.stitched_markdown_file.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
