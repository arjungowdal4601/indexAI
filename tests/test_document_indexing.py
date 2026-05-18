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
    TopicCandidate,
    TopicEntry,
    TopicMatchDecision,
)
from document_indexing.routers import route_after_state
from document_indexing.state import DocumentIndexingState
from document_indexing.storage import (
    load_processing_state,
    load_topic_index,
    read_page_manifest,
    read_page_window,
    write_topic_index,
)
from document_indexing.validator import validate_topic_index


class FakeIndexingClient:
    def extract_candidates(self, main_pages, context_pages, existing_topics):
        main_page_numbers = [page.page for page in main_pages]
        if main_page_numbers == [1, 2, 3]:
            return [
                TopicCandidate(
                    topic="Capital rules",
                    pages=[1, 2, 3],
                    description="Introduces the capital rules and reporting terms.",
                    keywords=[f"capital term {index}" for index in range(1, 18)],
                )
            ]
        return [
            TopicCandidate(
                topic="Capital buffer requirements",
                pages=[4, 5, 6],
                description="Continues capital rules with buffer and threshold requirements.",
                keywords=["capital buffer", "threshold", "supervisory review"],
            )
        ]

    def match_topics(self, candidates, current_index):
        decisions = []
        for candidate in candidates:
            decisions.append(
                TopicMatchDecision(
                    candidate_topic=candidate.topic,
                    decision="update_existing" if current_index else "add_new",
                    matched_topic=current_index[0].topic if current_index else None,
                    reason="same regulatory topic" if current_index else "new topic",
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

    def test_page_window_separates_main_pages_from_forward_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pages_dir = Path(temp_dir)
            for page_no in range(1, 6):
                (pages_dir / f"page_{page_no:04d}.md").write_text(
                    f"page {page_no}",
                    encoding="utf-8",
                )
            manifest = read_page_manifest(pages_dir)

            window = read_page_window(
                manifest=manifest,
                start_page=2,
                main_window_size=2,
                context_window_size=2,
            )

            self.assertEqual([page.page for page in window.main_pages], [2, 3])
            self.assertEqual([page.page for page in window.context_pages], [4, 5])
            self.assertEqual(window.main_pages[0].markdown, "page 2")

    def test_load_topic_index_returns_empty_list_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(load_topic_index(Path(temp_dir) / "topic_index.json"), [])

    def test_write_topic_index_creates_backup_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            original = [
                TopicEntry(
                    topic="Original",
                    pages=[1],
                    description="Original description.",
                    keywords=["original"],
                )
            ]
            updated = [
                TopicEntry(
                    topic="Updated",
                    pages=[1, 2],
                    description="Updated description.",
                    keywords=["updated"],
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
    def test_validator_allows_long_descriptions_and_full_keyword_lists(self):
        keywords = [f"Keyword {index}" for index in range(1, 19)]
        topics = [
            TopicEntry(
                topic="Capital Rules",
                pages=[3, 1, 3],
                description=" ".join(["word"] * 90),
                keywords=keywords + [" Keyword 1 ", ""],
            )
        ]

        report, cleaned = validate_topic_index(topics, token_limit=10)

        self.assertEqual(report.status, "passed")
        self.assertEqual(cleaned[0].pages, [1, 3])
        self.assertEqual(cleaned[0].keywords, keywords)
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

    def test_graph_indexes_two_windows_into_one_continuous_topic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pages_dir = root / "pages_md"
            output_dir = root / "indexing_output"
            pages_dir.mkdir()
            for page_no in range(1, 7):
                (pages_dir / f"page_{page_no:04d}.md").write_text(
                    f"Capital content on page {page_no}.",
                    encoding="utf-8",
                )

            output = run_document_indexing(
                pages_folder_path=pages_dir,
                output_folder_path=output_dir,
                document_id="capital-doc",
                main_window_size=3,
                context_window_size=2,
                client=FakeIndexingClient(),
            )

            topic_index = json.loads(output.topic_index_path.read_text())
            processing_state = json.loads(output.processing_state_path.read_text())
            log_text = output.revision_log_path.read_text(encoding="utf-8")

            self.assertEqual(len(topic_index), 1)
            self.assertEqual(topic_index[0]["topic"], "Capital rules")
            self.assertEqual(topic_index[0]["pages"], [1, 2, 3, 4, 5, 6])
            self.assertEqual(len(topic_index[0]["keywords"]), 20)
            self.assertIn("capital term 17", topic_index[0]["keywords"])
            self.assertIn("supervisory review", topic_index[0]["keywords"])
            self.assertNotIn("window", topic_index[0])
            self.assertEqual(processing_state["status"], "completed")
            self.assertIn("Main pages: 1-3", log_text)
            self.assertIn("Main pages: 4-6", log_text)


if __name__ == "__main__":
    unittest.main()
