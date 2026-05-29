import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

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
        return f"- table {request.table_id} page {request.page_no}"

    def describe_image(self, image_path: Path) -> str:
        self.image_paths.append(image_path)
        return f"Image description for {image_path.name}"

    def describe_formula(self, image_path: Path, formula_markdown: str) -> str:
        self.formula_requests.append((image_path, formula_markdown))
        return f"LaTeX: {formula_markdown.strip()}\nFormula description for {image_path.name}"


class FlakyImageClient(FakeEnrichmentClient):
    def __init__(self):
        super().__init__()
        self.image_attempts = 0

    def describe_image(self, image_path: Path) -> str:
        self.image_attempts += 1
        if self.image_attempts == 1:
            raise RuntimeError("Connection timeout")
        return super().describe_image(image_path)


def write_page_asset_registry(assets_dir: Path, pages: list[dict]) -> None:
    (assets_dir / "page_asset_registry.json").write_text(
        json.dumps({"schema_version": 1, "pages": pages}, indent=2),
        encoding="utf-8",
    )


def page_registry_entry(page: int, assets: list[dict]) -> dict:
    counts = {"picture": 0, "table": 0, "formula": 0}
    for asset in assets:
        counts[asset["kind"]] += 1
    return {
        "page": page,
        "markdown_path": f"pages_md/page_{page:04d}.md",
        "counts": counts,
        "assets": assets,
    }


def registry_asset(kind: str, path: str, page: int, local_index: int, global_index: int) -> dict:
    return {
        "kind": kind,
        "path": path,
        "source_page": page,
        "local_index": local_index,
        "global_index": global_index,
    }


class EnrichmentTests(unittest.TestCase):
    def test_enrich_document_appends_unresolved_picture_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (picture_dir / "picture-1.png").write_bytes(b"picture")
            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\nNo image placeholder here.\n",
                encoding="utf-8",
            )
            write_page_asset_registry(
                assets_dir,
                [
                    page_registry_entry(
                        1,
                        [registry_asset("picture", "image_png_images/picture-1.png", 1, 1, 1)],
                    )
                ],
            )

            output = enrich_document(assets_dir, client=FakeEnrichmentClient())
            readable = output.readable_markdown_file.read_text(encoding="utf-8")

            self.assertIn("Status: PARTIAL_AUTOMATION_VERIFY_REQUIRED", readable)
            self.assertIn("## Unresolved Assets (Page 1)", readable)
            self.assertIn("![Figure](image_png_images/picture-1.png)", readable)
            self.assertIn("reason: unmatched_picture_placeholder", readable)

    def test_enrich_document_appends_unresolved_table_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (table_dir / "table-1.png").write_bytes(b"table")
            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\nNo table here.\n",
                encoding="utf-8",
            )
            write_page_asset_registry(
                assets_dir,
                [
                    page_registry_entry(
                        1,
                        [registry_asset("table", "table_images/table-1.png", 1, 1, 1)],
                    )
                ],
            )

            output = enrich_document(assets_dir, client=FakeEnrichmentClient())
            readable = output.readable_markdown_file.read_text(encoding="utf-8")

            self.assertIn("Status: PARTIAL_AUTOMATION_VERIFY_REQUIRED", readable)
            self.assertIn("![Table](table_images/table-1.png)", readable)
            self.assertIn("reason: unmatched_table_block", readable)

    def test_enrich_document_appends_unresolved_formula_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (formula_dir / "formula-1.png").write_bytes(b"formula")
            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\nNo formula here.\n",
                encoding="utf-8",
            )
            write_page_asset_registry(
                assets_dir,
                [
                    page_registry_entry(
                        1,
                        [registry_asset("formula", "formula_images/formula-1.png", 1, 1, 1)],
                    )
                ],
            )

            output = enrich_document(assets_dir, client=FakeEnrichmentClient())
            readable = output.readable_markdown_file.read_text(encoding="utf-8")

            self.assertIn("Status: PARTIAL_AUTOMATION_VERIFY_REQUIRED", readable)
            self.assertIn("![Formula](formula_images/formula-1.png)", readable)
            self.assertIn("reason: unmatched_formula_block", readable)

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

    def test_enrich_document_writes_pages_without_previous_table_memory(self):
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
            write_page_asset_registry(
                assets_dir,
                [
                    page_registry_entry(
                        1,
                        [registry_asset("table", "table_images/table-1.png", 1, 1, 1)],
                    ),
                    page_registry_entry(
                        2,
                        [registry_asset("table", "table_images/table-2.png", 2, 1, 2)],
                    ),
                ],
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
            self.assertIn("- table table_001 page 1", page_1)
            self.assertIn("- table table_002 page 2", page_2)
            self.assertNotIn("| Col A | Col B |", page_1)
            self.assertEqual(len(client.table_requests), 2)
            self.assertFalse(hasattr(client.table_requests[0], "previous_markdown"))
            self.assertFalse(hasattr(client.table_requests[1], "previous_markdown"))
            self.assertFalse(hasattr(client.table_requests[1], "previous_image_path"))

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
            write_page_asset_registry(
                assets_dir,
                [
                    page_registry_entry(
                        1,
                        [
                            registry_asset("table", "table_images/table-1.png", 1, 1, 1),
                            registry_asset("picture", "image_png_images/picture-1.png", 1, 1, 1),
                            registry_asset("formula", "formula_images/formula-1.png", 1, 1, 1),
                        ],
                    )
                ],
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

    def test_enrich_document_retries_transient_image_description_and_emits_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (picture_dir / "picture-1.png").write_bytes(b"picture")
            (pages_dir / "page_0001.md").write_text(
                "\n\n--- PAGE 1 ---\n\n[[DOCLING_IMAGE]]\n",
                encoding="utf-8",
            )
            write_page_asset_registry(
                assets_dir,
                [
                    page_registry_entry(
                        1,
                        [registry_asset("picture", "image_png_images/picture-1.png", 1, 1, 1)],
                    )
                ],
            )
            events = []
            client = FlakyImageClient()

            with patch("doc_processing.retries.time.sleep", return_value=None):
                output = enrich_document(
                    assets_dir,
                    client=client,
                    event_callback=lambda *args: events.append(args),
                )

            page_1 = (output.pages_md_dir / "page_0001.md").read_text(encoding="utf-8")

        self.assertEqual(client.image_attempts, 2)
        self.assertIn("Image description for picture-1.png", page_1)
        self.assertTrue(any(event[1] == "waiting_for_llm" for event in events))
        self.assertTrue(any(event[1] == "retry" for event in events))

    def test_enrich_document_resume_skips_existing_enriched_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            (pages_dir / "page_0001.md").write_text("--- PAGE 1 ---\nraw", encoding="utf-8")
            write_page_asset_registry(
                assets_dir,
                [page_registry_entry(1, [])],
            )
            enriched_page = assets_dir.parent / "enriched_doc" / "pages_md" / "page_0001.md"
            enriched_page.parent.mkdir(parents=True)
            enriched_page.write_text("--- PAGE 1 ---\nalready enriched", encoding="utf-8")

            output = enrich_document(
                assets_dir,
                client=FakeEnrichmentClient(),
                resume=True,
            )

            self.assertEqual(enriched_page.read_text(encoding="utf-8"), "--- PAGE 1 ---\nalready enriched")
            self.assertIn(
                "already enriched",
                output.readable_markdown_file.read_text(encoding="utf-8"),
            )

    def test_enrich_document_uses_only_page_local_assets_and_appends_unresolved_tail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assets_dir = Path(temp_dir) / "sample_doc_assets" / "docling_assets"
            pages_dir = assets_dir / "pages_md"
            table_dir = assets_dir / "table_images"
            picture_dir = assets_dir / "image_png_images"
            formula_dir = assets_dir / "formula_images"
            for folder in [pages_dir, table_dir, picture_dir, formula_dir]:
                folder.mkdir(parents=True, exist_ok=True)

            for name in ["table-1.png", "table-2.png", "table-3.png"]:
                (table_dir / name).write_bytes(name.encode("utf-8"))
            for name in ["formula-1.png", "formula-2.png", "formula-3.png"]:
                (formula_dir / name).write_bytes(name.encode("utf-8"))

            (pages_dir / "page_0001.md").write_text("--- PAGE 1 ---\nraw only", encoding="utf-8")
            (pages_dir / "page_0002.md").write_text(
                "\n\n--- PAGE 2 ---\n\n"
                "| Col A | Col B |\n"
                "|---|---|\n"
                "| A1 | B1 |\n\n"
                "$$E = mc^2$$\n",
                encoding="utf-8",
            )
            (pages_dir / "page_0003.md").write_text(
                "\n\n--- PAGE 3 ---\n\n"
                "| Next | Page |\n"
                "|---|---|\n"
                "| N | P |\n\n"
                "$$F = ma$$\n",
                encoding="utf-8",
            )
            write_page_asset_registry(
                assets_dir,
                [
                    page_registry_entry(1, []),
                    page_registry_entry(
                        2,
                        [
                            registry_asset("table", "table_images/table-1.png", 2, 1, 1),
                            registry_asset("table", "table_images/table-2.png", 2, 2, 2),
                            registry_asset("formula", "formula_images/formula-1.png", 2, 1, 1),
                            registry_asset("formula", "formula_images/formula-2.png", 2, 2, 2),
                        ],
                    ),
                    page_registry_entry(
                        3,
                        [
                            registry_asset("table", "table_images/table-3.png", 3, 1, 3),
                            registry_asset("formula", "formula_images/formula-3.png", 3, 1, 3),
                        ],
                    ),
                ],
            )
            client = FakeEnrichmentClient()

            output = enrich_document(assets_dir, client=client)
            page_2 = (output.pages_md_dir / "page_0002.md").read_text(encoding="utf-8")
            page_3 = (output.pages_md_dir / "page_0003.md").read_text(encoding="utf-8")
            readable = output.readable_markdown_file.read_text(encoding="utf-8")

        self.assertIn("![Table](table_images/table-1.png)", page_2)
        self.assertIn("![Formula](formula_images/formula-1.png)", page_2)
        self.assertIn("![Table](table_images/table-2.png)", page_2)
        self.assertIn("![Formula](formula_images/formula-2.png)", page_2)
        self.assertIn("Status: PARTIAL_AUTOMATION_VERIFY_REQUIRED", page_2)
        self.assertIn("reason: unmatched_table_block", page_2)
        self.assertIn("reason: unmatched_formula_block", page_2)
        self.assertNotIn("table_images/table-3.png", page_2)
        self.assertNotIn("formula_images/formula-3.png", page_2)
        self.assertIn("![Table](table_images/table-3.png)", page_3)
        self.assertIn("![Formula](formula_images/formula-3.png)", page_3)
        self.assertIn("## Unresolved Assets (Page 2)", readable)
        self.assertEqual([request.current_image_path.name for request in client.table_requests], ["table-1.png", "table-2.png", "table-3.png"])
        self.assertEqual([path.name for path, _markdown in client.formula_requests], ["formula-1.png", "formula-2.png", "formula-3.png"])


if __name__ == "__main__":
    unittest.main()
