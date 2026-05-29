import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from doc_processing.docling_converter import convert_pdf_with_docling


class FakeImage:
    def __init__(self, payload):
        self.payload = payload

    def save(self, file, *_args, **_kwargs):
        file.write(self.payload)


class FakePictureItem:
    def __init__(self, page_no, payload=b"picture"):
        self.prov = [SimpleNamespace(page_no=page_no)]
        self.image = FakeImage(payload)

    def get_image(self, _doc):
        return self.image


class FakeTableItem:
    def __init__(self, page_no, payload=b"table"):
        self.prov = [SimpleNamespace(page_no=page_no)]
        self.image = FakeImage(payload)

    def get_image(self, _doc):
        return self.image


class FakeFormulaItem:
    def __init__(self, page_no, payload=b"formula"):
        self.prov = [SimpleNamespace(page_no=page_no)]
        self.image = FakeImage(payload)

    def get_image(self, _doc):
        return self.image


class FakeDoc:
    def __init__(self, page_no, items=None):
        self.page_no = page_no
        self.pages = {page_no: SimpleNamespace(image=None)}
        self.items = items or []

    def export_to_markdown(self, **_kwargs):
        return (
            f"# Page {self.page_no}\n\n"
            "| Col A | Col B |\n"
            "|---|---|\n"
            "| A1 | B1 |\n\n"
            "[[DOCLING_IMAGE]]\n\n"
            "$$E = mc^2$$\n"
        )

    def iterate_items(self):
        return iter((item, 0) for item in self.items)


class FakeConverter:
    def __init__(self, doc_factory=None):
        self.page_ranges = []
        self.doc_factory = doc_factory or (lambda page_no: FakeDoc(page_no))

    def convert(self, _pdf_path, page_range):
        self.page_ranges.append(page_range)
        return SimpleNamespace(document=self.doc_factory(page_range[0]))


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
            (asset_root / "page_asset_registry.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pages": [
                            {
                                "page": 1,
                                "markdown_path": "pages_md/page_0001.md",
                                "counts": {"picture": 0, "table": 0, "formula": 0},
                                "assets": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

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

    def test_conversion_writes_page_local_asset_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            fake_converter = FakeConverter(
                doc_factory=lambda page_no: FakeDoc(
                    page_no,
                    items=[
                        FakePictureItem(page_no, b"picture"),
                        FakeTableItem(page_no, b"table"),
                        FakeFormulaItem(page_no, b"formula"),
                    ],
                )
            )
            with patch(
                "doc_processing.docling_converter.build_docling_converter",
                return_value=fake_converter,
            ), patch(
                "doc_processing.docling_converter.PictureItem",
                FakePictureItem,
            ), patch(
                "doc_processing.docling_converter.TableItem",
                FakeTableItem,
            ), patch(
                "doc_processing.docling_converter.FormulaItem",
                FakeFormulaItem,
            ):
                output = convert_pdf_with_docling(pdf_path, page_range=(1, 2))

            registry_path = output.docling_assets_dir / "page_asset_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))

        self.assertEqual(registry["schema_version"], 1)
        self.assertEqual([page["page"] for page in registry["pages"]], [1, 2])
        self.assertEqual(registry["pages"][0]["markdown_path"], "pages_md/page_0001.md")
        self.assertEqual(
            registry["pages"][0]["counts"],
            {"picture": 1, "table": 1, "formula": 1},
        )
        self.assertEqual(
            [(asset["kind"], asset["path"], asset["source_page"], asset["local_index"], asset["global_index"]) for asset in registry["pages"][0]["assets"]],
            [
                ("picture", "image_png_images/picture-1.png", 1, 1, 1),
                ("table", "table_images/table-1.png", 1, 1, 1),
                ("formula", "formula_images/formula-1.png", 1, 1, 1),
            ],
        )
        self.assertEqual(
            [(asset["kind"], asset["path"], asset["source_page"], asset["local_index"], asset["global_index"]) for asset in registry["pages"][1]["assets"]],
            [
                ("picture", "image_png_images/picture-2.png", 2, 1, 2),
                ("table", "table_images/table-2.png", 2, 1, 2),
                ("formula", "formula_images/formula-2.png", 2, 1, 2),
            ],
        )
        for page in registry["pages"]:
            for asset in page["assets"]:
                self.assertNotIn("location_hint", asset)
                self.assertNotIn("line_start", asset)
                self.assertNotIn("line_end", asset)
                self.assertNotIn("ASSET", json.dumps(asset))

    def test_resume_reconverts_existing_page_when_registry_entry_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")
            asset_root = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = asset_root / "pages_md"
            pages_dir.mkdir(parents=True)
            (pages_dir / "page_0001.md").write_text("--- PAGE 1 ---\nexisting", encoding="utf-8")

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

            self.assertEqual(fake_converter.page_ranges, [(1, 1)])
            registry_path = output.docling_assets_dir / "page_asset_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(registry["pages"][0]["page"], 1)


if __name__ == "__main__":
    unittest.main()
