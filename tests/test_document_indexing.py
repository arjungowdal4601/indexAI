import json
import inspect
import tempfile
import unittest
from pathlib import Path

from document_indexing import run_document_indexing
from document_indexing.graph import export_graph_mermaid
from document_indexing.llm import LangChainTopicIndexingClient
from document_indexing.nodes import load_state_node, read_manifest_node
from document_indexing.prompts import (
    DESCRIPTION_UPDATE_PROMPT,
    TOPIC_EXTRACTION_PROMPT,
    TOPIC_MATCHING_PROMPT,
)
from document_indexing.schemas import (
    TopicAsset,
    TopicCandidateDraft,
    TopicEntry,
    TopicMatchDecision,
)
from document_indexing.routers import route_after_state
from document_indexing.state import DocumentIndexingState
from document_indexing.storage import (
    extract_page_assets,
    load_processing_state,
    load_topic_index,
    read_page_manifest,
    read_page_window,
    topics_for_page,
    write_topic_index,
)
from document_indexing.validator import validate_topic_index


class FakeIndexingClient:
    def extract_candidates(
        self,
        target_page,
        target_page_assets,
        previous_page_topics,
        next_page,
        existing_topics,
    ):
        if target_page.page == 1:
            return [
                TopicCandidateDraft(
                    topic="Neutral policy requirements",
                    description=(
                        "Introduces neutral policy requirements with exact "
                        "reporting conditions and Table A evidence."
                    ),
                    asset_paths=["table_images/table-1.png"],
                )
            ]
        previous_topic_names = [topic.topic for topic in previous_page_topics]
        if (
            target_page.page == 2
            and previous_topic_names == ["Neutral policy requirements"]
            and next_page is not None
            and next_page.page == 3
        ):
            return [
                TopicCandidateDraft(
                    topic="Neutral policy requirements",
                    description=(
                        "Continues neutral policy requirements with threshold "
                        "formula R = A / B and supervisory review conditions."
                    ),
                    asset_paths=[
                        "formula_images/formula-1.png",
                        "table_images/table-2.png",
                    ],
                )
            ]
        return [
            TopicCandidateDraft(
                topic="Unrelated final note",
                description="Captures a separate final note.",
                asset_paths=[],
            )
        ]

    def match_topics(self, candidates, current_index):
        decisions = []
        for candidate in candidates:
            should_update = (
                current_index
                and candidate.topic == current_index[0].topic
            )
            decisions.append(
                TopicMatchDecision(
                    candidate_topic=candidate.topic,
                    decision="update_existing" if should_update else "add_new",
                    matched_topic=current_index[0].topic if should_update else None,
                    reason="same topic" if should_update else "new topic",
                )
            )
        return decisions

    def merge_topic(self, existing_topic, candidate):
        return (
            "Explains capital rules across reporting, buffer, and threshold "
            "requirements."
        )


class DocumentIndexingStorageTests(unittest.TestCase):
    def test_manifest_sorts_pages_and_reports_missing_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pages_dir = Path(temp_dir)
            (pages_dir / "page_0003.md").write_text("p3", encoding="utf-8")
            (pages_dir / "page_0001.md").write_text("p1", encoding="utf-8")

            manifest = read_page_manifest(pages_dir)

            self.assertEqual([page.page for page in manifest.pages], [1, 3])
            self.assertEqual(manifest.total_pages, 3)
            self.assertEqual(manifest.missing_pages, [2])

    def test_topics_for_page_returns_only_matching_index_entries(self):
        topics = [
            TopicEntry(
                topic="Earlier topic",
                pages=[1, 2],
                description="Earlier topic description.",
                assets=[],
            ),
            TopicEntry(
                topic="Later topic",
                pages=[3],
                description="Later topic description.",
                assets=[],
            ),
        ]

        matching = topics_for_page(topics, 2)

        self.assertEqual([topic.topic for topic in matching], ["Earlier topic"])

    def test_page_window_reads_target_page_next_page_and_previous_indexed_topics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pages_dir = Path(temp_dir)
            for page_no in range(1, 6):
                (pages_dir / f"page_{page_no:04d}.md").write_text(
                    f"page {page_no}",
                    encoding="utf-8",
                )
            manifest = read_page_manifest(pages_dir)
            current_index = [
                TopicEntry(
                    topic="Previous indexed topic",
                    pages=[1],
                    description="Topic already assigned to the previous page.",
                    assets=[],
                ),
                TopicEntry(
                    topic="Target topic from earlier page",
                    pages=[2],
                    description="Topic already assigned to this page.",
                    assets=[],
                ),
            ]

            window = read_page_window(
                manifest=manifest,
                target_page=2,
                current_topic_index=current_index,
            )

            self.assertEqual(window.target_page.page, 2)
            self.assertEqual(window.target_page.markdown, "page 2")
            self.assertEqual(window.next_page.page, 3)
            self.assertEqual(window.next_page.markdown, "page 3")
            self.assertEqual(
                [topic.topic for topic in window.previous_page_topics],
                ["Previous indexed topic"],
            )

    def test_extract_page_assets_reads_target_markdown_assets(self):
        markdown = "\n".join(
            [
                "Intro text.",
                "![Figure](image_png_images/picture-1.png)",
                "A compact diagram showing the data flow through the block.",
                "",
                "![Formula](formula_images/formula-1.png)",
                "LaTeX: A=B/C",
                "This defines A as B divided by C.",
                "",
                "![Table](table_images/table-1.png)",
                "The table compares baseline and proposed scores.",
            ]
        )

        assets = extract_page_assets(page=4, markdown=markdown)

        self.assertEqual(
            assets,
            [
                TopicAsset(
                    page=4,
                    type="figure",
                    path="image_png_images/picture-1.png",
                    description="A compact diagram showing the data flow through the block.",
                ),
                TopicAsset(
                    page=4,
                    type="formula",
                    path="formula_images/formula-1.png",
                    description="LaTeX: A=B/C This defines A as B divided by C.",
                ),
                TopicAsset(
                    page=4,
                    type="table",
                    path="table_images/table-1.png",
                    description="The table compares baseline and proposed scores.",
                ),
            ],
        )

    def test_load_topic_index_returns_empty_list_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(load_topic_index(Path(temp_dir) / "topic_index.json"), [])

    def test_load_topic_index_ignores_legacy_keywords_and_defaults_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "topic_index.json"
            index_path.write_text(
                json.dumps(
                    [
                        {
                            "topic": "Legacy topic",
                            "pages": [1],
                            "description": "Legacy description.",
                            "keywords": ["legacy", "tag"],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            topics = load_topic_index(index_path)

            self.assertEqual(topics[0].topic, "Legacy topic")
            self.assertEqual(topics[0].assets, [])

    def test_write_topic_index_creates_backup_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            original = [
                TopicEntry(
                    topic="Original",
                    pages=[1],
                    description="Original description.",
                    assets=[],
                )
            ]
            updated = [
                TopicEntry(
                    topic="Updated",
                    pages=[1, 2],
                    description="Updated description.",
                    assets=[
                        TopicAsset(
                            page=2,
                            type="formula",
                            path="formula_images/formula-1.png",
                            description="Important formula.",
                        )
                    ],
                )
            ]

            write_topic_index(output_dir, original, step_number=1)
            write_topic_index(output_dir, updated, step_number=2)

            index_data = json.loads((output_dir / "topic_index.json").read_text())
            backup_data = json.loads(
                (
                    output_dir
                    / "backups"
                    / "topic_index_before_step_0002.json"
                ).read_text()
            )
            self.assertEqual(index_data[0]["topic"], "Updated")
            self.assertIn("assets", index_data[0])
            self.assertNotIn("keywords", index_data[0])
            self.assertEqual(backup_data[0]["topic"], "Original")

    def test_load_processing_state_resumes_existing_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            state_path = output_dir / "processing_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "document_id": "doc-1",
                        "last_completed_page": 3,
                        "next_start_page": 4,
                        "main_window_size": 3,
                        "context_window_size": 2,
                        "status": "in_progress",
                    }
                ),
                encoding="utf-8",
            )

            state = load_processing_state(
                output_dir=output_dir,
                document_id="doc-1",
                main_window_size=3,
                context_window_size=2,
            )

            self.assertEqual(state.next_start_page, 4)
            self.assertEqual(state.status, "in_progress")


class DocumentIndexingValidatorTests(unittest.TestCase):
    def test_validator_allows_rich_descriptions_and_deduplicates_assets(self):
        topics = [
            TopicEntry(
                topic="Capital Rules",
                pages=[3, 1, 3],
                description=" ".join(["word"] * 90),
                assets=[
                    TopicAsset(
                        page=3,
                        type="formula",
                        path=" formula_images/formula-1.png ",
                        description=" Capital ratio formula. ",
                    ),
                    TopicAsset(
                        page=3,
                        type="formula",
                        path="formula_images/formula-1.png",
                        description="Capital ratio formula.",
                    ),
                ],
            )
        ]

        report, cleaned = validate_topic_index(topics, token_limit=10)

        self.assertEqual(report.status, "passed")
        self.assertEqual(cleaned[0].pages, [1, 3])
        self.assertEqual(len(cleaned[0].assets), 1)
        self.assertEqual(cleaned[0].assets[0].path, "formula_images/formula-1.png")
        self.assertNotIn("description_too_long: Capital Rules", report.warnings)
        self.assertIn("token_budget_exceeded", report.warnings)


class DocumentIndexingPromptTests(unittest.TestCase):
    def test_llm_client_uses_langchain_structured_output_chains(self):
        self.assertEqual(
            TOPIC_EXTRACTION_PROMPT.__class__.__name__,
            "ChatPromptTemplate",
        )
        self.assertEqual(
            TOPIC_MATCHING_PROMPT.__class__.__name__,
            "ChatPromptTemplate",
        )
        self.assertEqual(
            DESCRIPTION_UPDATE_PROMPT.__class__.__name__,
            "ChatPromptTemplate",
        )

        source = inspect.getsource(LangChainTopicIndexingClient)

        self.assertIn("with_structured_output(TopicCandidateList)", source)
        self.assertIn("with_structured_output(TopicMatchDecisionList)", source)
        self.assertIn("with_structured_output(TopicDescriptionUpdate)", source)
        self.assertIn("DOC_INDEXING_MODEL", source)
        self.assertIn("OPENAI_MODEL", source)
        self.assertIn("DEFAULT_ENRICHMENT_MODEL", source)
        self.assertNotIn("from openai", source)

    def test_topic_extraction_prompt_uses_generic_target_page_contract(self):
        prompt_text = str(TOPIC_EXTRACTION_PROMPT)

        self.assertIn("previous_page_indexed_topics", prompt_text)
        self.assertIn("target_page_assets", prompt_text)
        self.assertIn("target_page_markdown", prompt_text)
        self.assertIn("next_page_markdown", prompt_text)
        self.assertIn("index only the target page", prompt_text.lower())
        self.assertIn("never include previous or next page numbers", prompt_text.lower())
        self.assertIn("do not return keywords", prompt_text.lower())
        self.assertNotIn("Transformer", prompt_text)
        self.assertNotIn("scaled dot-product", prompt_text.lower())
        self.assertNotIn("Attention(Q,K,V)", prompt_text)


class DocumentIndexingGraphTests(unittest.TestCase):
    def test_graph_components_are_split_into_readable_modules(self):
        self.assertEqual(DocumentIndexingState.__name__, "DocumentIndexingState")
        self.assertTrue(callable(load_state_node))
        self.assertTrue(callable(read_manifest_node))
        self.assertTrue(callable(route_after_state))

    def test_exports_mermaid_graph_with_langgraph_renderer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "document_indexing_graph.mmd"

            export_graph_mermaid(output_path)

            mermaid = output_path.read_text(encoding="utf-8")
            self.assertIn("load_state", mermaid)
            self.assertIn("read_manifest", mermaid)
            self.assertIn("write_outputs", mermaid)

    def test_graph_indexes_adjacent_target_pages_into_one_continuous_topic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pages_dir = root / "pages_md"
            output_dir = root / "indexing_output"
            pages_dir.mkdir()
            (pages_dir / "page_0001.md").write_text(
                "\n".join(
                    [
                        "Neutral policy content on page 1.",
                        "![Table](table_images/table-1.png)",
                        "The table summarizes reporting conditions.",
                    ]
                ),
                encoding="utf-8",
            )
            (pages_dir / "page_0002.md").write_text(
                "\n".join(
                    [
                        "Neutral policy content on page 2.",
                        "![Formula](formula_images/formula-1.png)",
                        "LaTeX: R=A/B",
                        "This defines the threshold ratio.",
                    ]
                ),
                encoding="utf-8",
            )
            (pages_dir / "page_0003.md").write_text(
                "\n".join(
                    [
                        "Neutral policy content on page 3.",
                        "![Table](table_images/table-2.png)",
                        "The next page table must not attach to page 2.",
                    ]
                ),
                encoding="utf-8",
            )

            output = run_document_indexing(
                pages_folder_path=pages_dir,
                output_folder_path=output_dir,
                document_id="capital-doc",
                main_window_size=1,
                context_window_size=1,
                client=FakeIndexingClient(),
            )

            topic_index = json.loads(output.topic_index_path.read_text())
            processing_state = json.loads(output.processing_state_path.read_text())
            log_text = output.revision_log_path.read_text(encoding="utf-8")

            self.assertEqual(len(topic_index), 2)
            self.assertEqual(topic_index[0]["topic"], "Neutral policy requirements")
            self.assertEqual(topic_index[0]["pages"], [1, 2])
            self.assertNotIn(3, topic_index[0]["pages"])
            self.assertNotIn("keywords", topic_index[0])
            self.assertEqual(
                topic_index[0]["assets"],
                [
                    {
                        "page": 1,
                        "type": "table",
                        "path": "table_images/table-1.png",
                        "description": "The table summarizes reporting conditions.",
                    },
                    {
                        "page": 2,
                        "type": "formula",
                        "path": "formula_images/formula-1.png",
                        "description": "LaTeX: R=A/B This defines the threshold ratio.",
                    },
                ],
            )
            self.assertNotIn("table_images/table-2.png", json.dumps(topic_index))
            self.assertNotIn("window", topic_index[0])
            self.assertEqual(processing_state["status"], "completed")
            self.assertIn("Target page: 1", log_text)
            self.assertIn("Target page: 2", log_text)
            self.assertIn("Previous page indexed topics: Neutral policy requirements", log_text)
            self.assertIn("Next context page: 3", log_text)


if __name__ == "__main__":
    unittest.main()
