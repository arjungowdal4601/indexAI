import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_retrieval import run_document_retrieval
from document_retrieval.graph import export_graph_mermaid
from document_retrieval.llm import LangChainRetrievalClient
from document_retrieval.main import format_retrieval_output, run_retrieval_pipeline
from document_retrieval.nodes import check_page_files_exist_node, estimate_context_size_node
from document_retrieval.prompts import (
    ANSWER_FROM_COMPRESSED_EVIDENCE_PROMPT,
    ANSWER_FROM_PAGES_PROMPT,
    COMPRESS_PAGE_EVIDENCE_PROMPT,
    ROUTE_QUERY_TO_TOPICS_PROMPT,
)
from document_retrieval.schemas import (
    FinalAnswer,
    PageContext,
    PageEvidence,
    RetrievalOutput,
    RetrievalTrace,
    RoutingDecision,
    TopicAsset,
    TopicEntry,
    TopicRoute,
)
from document_retrieval.storage import load_topic_index, read_selected_page_markdowns


class FakeRetrievalClient:
    def __init__(self):
        self.direct_called = False
        self.compressed_called = False
        self.compressed_pages = []

    def route_query_to_topics(self, user_query, topic_index_json):
        topics = json.loads(topic_index_json)
        selected = sorted({page for topic in topics for page in topic["pages"]})
        return RoutingDecision(
            routes=[
                TopicRoute(
                    topic=topics[0]["topic"],
                    pages=selected,
                    reason="The topic matches the full query.",
                    confidence="high",
                )
            ],
            selected_pages=selected,
            overall_reason="The selected topic covers the query.",
        )

    def compress_page_evidence(self, user_query, page_context):
        self.compressed_pages.append(page_context.page)
        return PageEvidence(
            page=page_context.page,
            useful=True,
            evidence=f"Evidence from page {page_context.page}.",
            key_terms=["attention"],
        )

    def answer_from_pages(self, user_query, page_context, retrieval_trace):
        self.direct_called = True
        self.direct_page_context = page_context
        self.direct_trace = retrieval_trace
        return FinalAnswer(
            answer="Direct answer from selected pages [p. 1].",
            pages_used=[1],
            missing_information=[],
        )

    def answer_from_compressed_evidence(
        self,
        user_query,
        compressed_evidence,
        retrieval_trace,
    ):
        self.compressed_called = True
        self.compressed_evidence = compressed_evidence
        self.compressed_trace = retrieval_trace
        return FinalAnswer(
            answer="Compressed answer from selected evidence [p. 1].",
            pages_used=[1],
            missing_information=[],
        )


def write_topic_index(path: Path, pages: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "topic": "Attention mechanisms",
                    "pages": pages,
                    "description": (
                        "Explains attention mechanisms with exact Q/K/V terminology "
                        "and page-level formula or figure assets when present."
                    ),
                    "assets": [
                        {
                            "page": pages[0],
                            "type": "figure",
                            "path": "image_png_images/picture-1.png",
                            "description": "Diagram showing the attention data flow.",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )


def write_pages(folder: Path, pages: list[int], markdown: str = "Page text.") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for page_no in pages:
        (folder / f"page_{page_no:04d}.md").write_text(
            f"{markdown} Page {page_no}.",
            encoding="utf-8",
        )


class DocumentRetrievalStorageTests(unittest.TestCase):
    def test_load_topic_index_validates_root_list_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            topic_index_path = Path(temp_dir) / "topic_index.json"
            topic_index_path.write_text(
                json.dumps(
                    {
                        "topic": "Not a list",
                        "pages": [1],
                        "description": "Invalid root.",
                        "assets": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Topic index root must be a list"):
                load_topic_index(topic_index_path)

    def test_load_topic_index_returns_validated_topic_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            topic_index_path = Path(temp_dir) / "topic_index.json"
            write_topic_index(topic_index_path, pages=[2, 1])

            topics = load_topic_index(topic_index_path)

            self.assertEqual(
                topics,
                [
                    TopicEntry(
                        topic="Attention mechanisms",
                        pages=[2, 1],
                        description=(
                            "Explains attention mechanisms with exact Q/K/V "
                            "terminology and page-level formula or figure assets "
                            "when present."
                        ),
                        assets=[
                            TopicAsset(
                                page=2,
                                type="figure",
                                path="image_png_images/picture-1.png",
                                description="Diagram showing the attention data flow.",
                            )
                        ],
                    )
                ],
            )

    def test_load_topic_index_ignores_legacy_keywords(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            topic_index_path = Path(temp_dir) / "topic_index.json"
            topic_index_path.write_text(
                json.dumps(
                    [
                        {
                            "topic": "Legacy attention",
                            "pages": [1],
                            "description": "Legacy description.",
                            "keywords": ["attention", "Transformer"],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            topics = load_topic_index(topic_index_path)

            self.assertEqual(topics[0].topic, "Legacy attention")
            self.assertEqual(topics[0].assets, [])

    def test_read_selected_pages_reads_only_requested_page_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pages_dir = Path(temp_dir)
            write_pages(pages_dir, [1, 2, 3])

            contexts = read_selected_page_markdowns(pages_dir, selected_pages=[3, 1])

            self.assertEqual([context.page for context in contexts], [3, 1])
            self.assertEqual([context.path.name for context in contexts], ["page_0003.md", "page_0001.md"])
            self.assertIn("Page 3.", contexts[0].markdown)
            self.assertNotIn("Page 2.", "\n".join(context.markdown for context in contexts))


class DocumentRetrievalNodeTests(unittest.TestCase):
    def test_check_page_files_exist_raises_clear_error_for_missing_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pages_dir = Path(temp_dir)
            write_pages(pages_dir, [1])

            with self.assertRaisesRegex(FileNotFoundError, "page_0002.md"):
                check_page_files_exist_node(
                    {
                        "pages_folder_path": pages_dir,
                        "selected_pages": [1, 2],
                    }
                )

    def test_estimate_context_size_selects_direct_or_compressed_mode(self):
        small_context = [
            PageContext(page=1, path=Path("page_0001.md"), markdown="short text"),
        ]
        large_context = [
            PageContext(page=1, path=Path("page_0001.md"), markdown="x" * 200),
            PageContext(page=2, path=Path("page_0002.md"), markdown="x" * 200),
        ]

        direct = estimate_context_size_node(
            {
                "page_contexts": small_context,
                "max_direct_pages": 1,
                "max_direct_estimated_tokens": 100,
            }
        )
        compressed = estimate_context_size_node(
            {
                "page_contexts": large_context,
                "max_direct_pages": 1,
                "max_direct_estimated_tokens": 1000,
            }
        )

        self.assertEqual(direct["memory_mode"], "direct")
        self.assertEqual(compressed["memory_mode"], "compressed")
        self.assertGreater(compressed["estimated_context_tokens"], direct["estimated_context_tokens"])


class DocumentRetrievalPromptTests(unittest.TestCase):
    def test_prompts_and_client_use_langchain_structured_output(self):
        self.assertEqual(ROUTE_QUERY_TO_TOPICS_PROMPT.__class__.__name__, "ChatPromptTemplate")
        self.assertEqual(COMPRESS_PAGE_EVIDENCE_PROMPT.__class__.__name__, "ChatPromptTemplate")
        self.assertEqual(ANSWER_FROM_PAGES_PROMPT.__class__.__name__, "ChatPromptTemplate")
        self.assertEqual(
            ANSWER_FROM_COMPRESSED_EVIDENCE_PROMPT.__class__.__name__,
            "ChatPromptTemplate",
        )

        source = inspect.getsource(LangChainRetrievalClient)

        self.assertIn("ChatOpenAI", source)
        self.assertIn("DOC_RETRIEVAL_MODEL", source)
        self.assertIn("with_structured_output(RoutingDecision)", source)
        self.assertIn("with_structured_output(PageEvidence)", source)
        self.assertIn("with_structured_output(FinalAnswer)", source)
        self.assertNotIn("from openai", source)

    def test_router_prompt_mentions_assets_not_keywords(self):
        prompt_text = str(ROUTE_QUERY_TO_TOPICS_PROMPT)

        self.assertIn("assets", prompt_text.lower())
        self.assertIn("figure", prompt_text.lower())
        self.assertIn("table", prompt_text.lower())
        self.assertIn("formula", prompt_text.lower())
        self.assertNotIn("keywords", prompt_text.lower())


class DocumentRetrievalGraphTests(unittest.TestCase):
    def test_exports_mermaid_graph_with_retrieval_nodes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "document_retrieval_graph.mmd"

            export_graph_mermaid(output_path)

            mermaid = output_path.read_text(encoding="utf-8")
            self.assertIn("load_topic_index", mermaid)
            self.assertIn("route_query_to_topics", mermaid)
            self.assertIn("answer_from_pages", mermaid)
            self.assertIn("answer_from_compressed_evidence", mermaid)

    def test_graph_answers_directly_with_selected_page_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            topic_index_path = root / "indexing_output" / "topic_index.json"
            pages_dir = root / "enriched_doc" / "pages_md"
            write_topic_index(topic_index_path, pages=[1, 2])
            write_pages(pages_dir, [1, 2])
            client = FakeRetrievalClient()

            output = run_document_retrieval(
                user_query="Explain attention.",
                topic_index_path=topic_index_path,
                pages_folder_path=pages_dir,
                client=client,
                max_direct_pages=10,
                max_direct_estimated_tokens=1000,
            )

            self.assertIsInstance(output, RetrievalOutput)
            self.assertEqual(output.final_answer.answer, "Direct answer from selected pages [p. 1].")
            self.assertEqual(output.retrieval_trace.memory_mode, "direct")
            self.assertEqual(output.retrieval_trace.matched_topics, ["Attention mechanisms"])
            self.assertEqual(output.retrieval_trace.pages_read, [1, 2])
            self.assertEqual(output.retrieval_trace.files_read, ["page_0001.md", "page_0002.md"])
            self.assertTrue(client.direct_called)
            self.assertFalse(client.compressed_called)
            self.assertIn("PAGE 1", client.direct_page_context)

    def test_graph_compresses_evidence_when_page_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            topic_index_path = root / "indexing_output" / "topic_index.json"
            pages_dir = root / "enriched_doc" / "pages_md"
            write_topic_index(topic_index_path, pages=[1, 2])
            write_pages(pages_dir, [1, 2])
            client = FakeRetrievalClient()

            output = run_document_retrieval(
                user_query="Explain attention.",
                topic_index_path=topic_index_path,
                pages_folder_path=pages_dir,
                client=client,
                max_direct_pages=1,
                max_direct_estimated_tokens=1000,
            )

            self.assertEqual(output.final_answer.answer, "Compressed answer from selected evidence [p. 1].")
            self.assertEqual(output.retrieval_trace.memory_mode, "compressed")
            self.assertEqual(client.compressed_pages, [1, 2])
            self.assertFalse(client.direct_called)
            self.assertTrue(client.compressed_called)
            self.assertIn("Evidence from page 1.", client.compressed_evidence)


class DocumentRetrievalRunnerTests(unittest.TestCase):
    def test_runner_uses_retrieval_defaults_without_processing_or_indexing_pipeline(self):
        expected_output = RetrievalOutput(
            final_answer=FinalAnswer(
                answer="Answer [p. 1].",
                pages_used=[1],
                missing_information=[],
            ),
            retrieval_trace=RetrievalTrace(
                matched_topics=["Attention mechanisms"],
                pages_read=[1],
                files_read=["page_0001.md"],
                memory_mode="direct",
                selection_reason="Selected from topic index.",
            ),
        )

        with patch(
            "document_retrieval.main.run_document_retrieval",
            return_value=expected_output,
        ) as run_retrieval:
            output = run_retrieval_pipeline("Explain attention.")

        self.assertEqual(output, expected_output)
        run_retrieval.assert_called_once()
        kwargs = run_retrieval.call_args.kwargs
        self.assertEqual(kwargs["user_query"], "Explain attention.")
        self.assertTrue(str(kwargs["topic_index_path"]).endswith("sample_doc_assets\\indexing_output\\topic_index.json"))
        self.assertTrue(str(kwargs["pages_folder_path"]).endswith("sample_doc_assets\\enriched_doc\\pages_md"))

    def test_format_retrieval_output_prints_trace_answer_and_missing_information(self):
        output = RetrievalOutput(
            final_answer=FinalAnswer(
                answer="Answer from evidence [p. 2].",
                pages_used=[2],
                missing_information=["No rejection condition found."],
            ),
            retrieval_trace=RetrievalTrace(
                matched_topics=["Attention mechanisms"],
                pages_read=[2],
                files_read=["page_0002.md"],
                memory_mode="compressed",
                selection_reason="Selected from topic index.",
            ),
        )

        text = format_retrieval_output(output)

        self.assertIn("## Retrieval Trace", text)
        self.assertIn("- Attention mechanisms", text)
        self.assertIn("Memory mode: compressed", text)
        self.assertIn("## Answer", text)
        self.assertIn("Answer from evidence [p. 2].", text)
        self.assertIn("Pages used: 2", text)
        self.assertIn("- No rejection condition found.", text)


if __name__ == "__main__":
    unittest.main()
