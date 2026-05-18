import tempfile
import unittest
from pathlib import Path

from doc_processing.enrichment import (
    TableDescriptionRequest,
    enrich_document,
    replace_formula_blocks,
    replace_image_placeholders,
)


class FakeEnrichmentClient:
    def __init__(self):
        self.table_requests = []
        self.image_paths = []
        self.formula_requests = []

    def describe_table(self, request: TableDescriptionRequest) -> str:
        self.table_requests.append(request)
        memory = "with memory" if request.previous_markdown else "without memory"
        return f"- table {request.table_id} page {request.page_no} {memory}"

    def describe_image(self, image_path: Path) -> str:
        self.image_paths.append(image_path)
        return f"Image description for {image_path.name}"

    def describe_formula(self, image_path: Path, formula_markdown: str) -> str:
        self.formula_requests.append((image_path, formula_markdown))
        return f"LaTeX: {formula_markdown.strip()}\nFormula description for {image_path.name}"


class EnrichmentTests(unittest.TestCase):
    def test_enrich_document_fails_fast_when_picture_asset_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\n[[DOCLING_IMAGE]]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "Picture asset count mismatch"):
                enrich_document(assets_dir, client=FakeEnrichmentClient())

            self.assertFalse(
                (assets_dir.parent / "enriched_doc" / "readable_processed_doc.md").exists()
            )

    def test_enrich_document_fails_fast_when_table_asset_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\n"
                "| Col A | Col B |\n"
                "|---|---|\n"
                "| A1 | B1 |\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "Table asset count mismatch"):
                enrich_document(assets_dir, client=FakeEnrichmentClient())

            self.assertFalse(
                (assets_dir.parent / "enriched_doc" / "readable_processed_doc.md").exists()
            )

    def test_enrich_document_fails_fast_when_formula_asset_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\n$$E = mc^2$$\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "Formula asset count mismatch"):
                enrich_document(assets_dir, client=FakeEnrichmentClient())

            self.assertFalse(
                (assets_dir.parent / "enriched_doc" / "readable_processed_doc.md").exists()
            )

    def test_replaces_image_placeholders_in_asset_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir) / "image_png_images"
            asset_dir.mkdir()
            image_path = asset_dir / "picture-1.png"
            image_path.write_bytes(b"image")
            client = FakeEnrichmentClient()

            rendered = replace_image_placeholders(
                markdown="Before\n[[DOCLING_IMAGE]]\nAfter",
                image_paths=iter([image_path]),
                client=client,
            )

            self.assertIn("![Figure](image_png_images/picture-1.png)", rendered)
            self.assertIn("Image description for picture-1.png", rendered)
            self.assertNotIn("[[DOCLING_IMAGE]]", rendered)
            self.assertEqual(client.image_paths, [image_path])

    def test_replaces_formula_blocks_in_asset_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            formula_dir = Path(temp_dir) / "formula_images"
            formula_dir.mkdir()
            formula_path = formula_dir / "formula-1.png"
            formula_path.write_bytes(b"formula")
            client = FakeEnrichmentClient()

            rendered = replace_formula_blocks(
                markdown="Before\n$$E = mc^2$$\nAfter",
                formula_paths=iter([formula_path]),
                client=client,
            )

            self.assertIn("![Formula](formula_images/formula-1.png)", rendered)
            self.assertIn("LaTeX: $$E = mc^2$$", rendered)
            self.assertNotIn("$$E = mc^2$$\nAfter", rendered)
            self.assertEqual(client.formula_requests[0][0], formula_path)

    def test_enrich_document_writes_pages_and_uses_table_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (table_dir / "table-1.png").write_bytes(b"table-1")
            (table_dir / "table-2.png").write_bytes(b"table-2")

            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\n"
                "| Col A | Col B |\n"
                "|---|---|\n"
                "| A1 | B1 |\n",
                encoding="utf-8",
            )
            (pages_dir / "page_0002.md").write_text(
                "\n\n--- PAGE 2 ---\n\n"
                "| A2 | B2 |\n"
                "| A3 | B3 |\n",
                encoding="utf-8",
            )

            client = FakeEnrichmentClient()
            output = enrich_document(assets_dir, client=client)

            self.assertTrue((output.pages_md_dir / "page_0001.md").exists())
            self.assertTrue((output.pages_md_dir / "page_0002.md").exists())
            self.assertTrue(output.readable_markdown_file.exists())

            page_1 = (output.pages_md_dir / "page_0001.md").read_text(encoding="utf-8")
            page_2 = (output.pages_md_dir / "page_0002.md").read_text(encoding="utf-8")
            readable = output.readable_markdown_file.read_text(encoding="utf-8")

            self.assertIn("![Table](table_images/table-1.png)", page_1)
            self.assertIn("![Table](table_images/table-2.png)", page_2)
            self.assertIn("![Table](table_images/table-1.png)", readable)
            self.assertIn("![Table](table_images/table-2.png)", readable)
            self.assertIn("- table table_001 page 1 without memory", page_1)
            self.assertIn("- table table_001 page 2 with memory", page_2)
            self.assertNotIn("| Col A | Col B |", page_1)
            self.assertEqual(len(client.table_requests), 2)
            self.assertIsNone(client.table_requests[0].previous_markdown)
            self.assertEqual(
                client.table_requests[1].previous_image_path,
                table_dir / "table-1.png",
            )
            self.assertIn("| Col A | Col B |", client.table_requests[1].previous_markdown)

    def test_enrich_document_copies_visual_asset_folders_next_to_readable_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (table_dir / "table-1.png").write_bytes(b"table")
            (picture_dir / "picture-1.png").write_bytes(b"picture")
            (formula_dir / "formula-1.png").write_bytes(b"formula")
            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\n"
                "| Col A | Col B |\n"
                "|---|---|\n"
                "| A1 | B1 |\n\n"
                "[[DOCLING_IMAGE]]\n\n"
                "$$E = mc^2$$\n",
                encoding="utf-8",
            )

            output = enrich_document(assets_dir, client=FakeEnrichmentClient())

            self.assertTrue((output.enriched_doc_dir / "table_images" / "table-1.png").exists())
            self.assertTrue(
                (output.enriched_doc_dir / "image_png_images" / "picture-1.png").exists()
            )
            self.assertTrue(
                (output.enriched_doc_dir / "formula_images" / "formula-1.png").exists()
            )

            readable = output.readable_markdown_file.read_text(encoding="utf-8")
            self.assertIn("![Table](table_images/table-1.png)", readable)
            self.assertIn("![Figure](image_png_images/picture-1.png)", readable)
            self.assertIn("![Formula](formula_images/formula-1.png)", readable)


if __name__ == "__main__":
    unittest.main()
