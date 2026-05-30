import json
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_indexing import run_document_indexing
from document_indexing.llm import (
    LangChainTopicIndexingClient,
    build_extraction_payload,
    build_matching_payload,
)
from document_indexing.prompts import (
    DESCRIPTION_UPDATE_PROMPT,
    TOPIC_EXTRACTION_PROMPT,
    TOPIC_MATCHING_PROMPT,
)
from document_indexing.schemas import (
    TopicAsset,
    TopicCandidate,
    TopicCandidateDraft,
    TopicEntry,
    TopicMatchDecision,
    PageMarkdown,
)
from document_indexing.storage import (
    extract_page_assets,
    load_processing_state,
    load_topic_index,
    read_page_manifest,
    read_page_window,
    topics_for_page,
    write_processing_state,
    write_topic_index,
)
from document_indexing.steps import update_topic_index
from document_indexing.schemas import ProcessingState


class FakeIndexingClient:
    def extract_candidates(
        self,
        target_page,
        target_page_assets,
        previous_page_topics,
        next_page,
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
        for slot, candidate in enumerate(candidates):
            should_update = (
                current_index
                and candidate.topic == current_index[0].topic
            )
            decisions.append(
                TopicMatchDecision(
                    candidate_batch_slot=slot,
                    decision="update_existing" if should_update else "no_match",
                    matched_batch_slot=0 if should_update else None,
                    reason="same topic" if should_update else "new topic",
                )
            )
        return decisions

    def merge_topic(self, existing_topic, candidate):
        return (
            "Explains capital rules across reporting, buffer, and threshold "
            "requirements."
        )


class FlakyExtractIndexingClient(FakeIndexingClient):
    def __init__(self):
        self.extract_attempts = 0

    def extract_candidates(self, *args, **kwargs):
        self.extract_attempts += 1
        if self.extract_attempts == 1:
            raise RuntimeError("Connection timeout 503")
        return super().extract_candidates(*args, **kwargs)


def make_topic(topic, page, description=None, assets=None):
    return TopicEntry(
        topic=topic,
        pages=[page],
        description=description or f"{topic} description.",
        assets=assets or [],
    )


def make_candidate(topic, page=9, description=None, assets=None):
    return TopicCandidate(
        topic=topic,
        pages=[page],
        description=description or f"{topic} candidate description.",
        assets=assets or [],
    )


def make_asset(page=9, path="table_images/table-9.png"):
    return TopicAsset(
        page=page,
        type="table",
        path=path,
        description=f"Asset at {path}.",
    )


def update_decision(candidate_slot, matched_slot):
    return TopicMatchDecision(
        candidate_batch_slot=candidate_slot,
        decision="update_existing",
        matched_batch_slot=matched_slot,
        reason="same topic",
    )


def no_match_decision(candidate_slot):
    return TopicMatchDecision(
        candidate_batch_slot=candidate_slot,
        decision="no_match",
        matched_batch_slot=None,
        reason="not in this batch",
    )


class BatchMatchingClient:
    def __init__(self, response_builder):
        self.response_builder = response_builder
        self.match_calls = []
        self.match_payloads = []
        self.merge_calls = []

    def match_topics(self, candidates, current_index):
        self.match_calls.append(
            {
                "candidate_topics": [candidate.topic for candidate in candidates],
                "existing_topics": [topic.topic for topic in current_index],
            }
        )
        self.match_payloads.append(
            json.loads(
                build_matching_payload(
                    candidates=candidates,
                    existing_topics=current_index,
                )
            )
        )
        return self.response_builder(
            len(self.match_calls),
            candidates,
            current_index,
        )

    def merge_topic(self, existing_topic, candidate):
        self.merge_calls.append((existing_topic.topic, candidate.topic))
        return f"{existing_topic.description} {candidate.description}"


class DocumentIndexingStorageTests(unittest.TestCase):
    def test_agent_memory_guide_builder_writes_agent_first_retrieval_contract(self):
        from document_indexing.agent_guide import build_agent_memory_guide

        guide = build_agent_memory_guide(
            document_id="doc_000001",
            filename="handbook.pdf",
            total_pages=7,
            topic_index=[
                TopicEntry(
                    topic="Capital controls",
                    pages=[1, 2, 3, 7],
                    description="Explains capital controls and reporting thresholds.",
                    assets=[],
                )
            ],
            manifest={
                "topic_index_path": "indexing_output/topic_index.json",
                "agent_md_path": "indexing_output/agent.md",
                "enriched_pages_folder": "enriched_doc/pages_md",
                "page_images_folder": "page_images",
            },
        )

        self.assertIn("# Agent Memory Guide", guide)
        self.assertIn("- document_id: doc_000001", guide)
        self.assertIn("- filename: handbook.pdf", guide)
        self.assertIn("- total pages: 7", guide)
        self.assertIn("Read `indexing_output/topic_index.json` first.", guide)
        self.assertIn("Do not read the whole document by default.", guide)
        self.assertIn(
            "Read only `enriched_doc/pages_md/page_XXXX.md` for those pages.",
            guide,
        )
        self.assertIn("- topic index: `indexing_output/topic_index.json`", guide)
        self.assertIn("- agent guide: `indexing_output/agent.md`", guide)
        self.assertIn("- enriched pages folder: `enriched_doc/pages_md`", guide)
        self.assertIn("- page images folder: `page_images`", guide)
        self.assertIn(
            "- Capital controls | pages 1-3, 7 | Explains capital controls and reporting thresholds.",
            guide,
        )
        self.assertIn("no direct indexed match was found", guide)

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

    def test_write_topic_index_cleans_topics_without_default_backups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            topics = [
                TopicEntry(
                    topic=" Updated ",
                    pages=[3, 1, 3],
                    description=" Updated description. ",
                    assets=[
                        TopicAsset(
                            page=2,
                            type="formula",
                            path=" formula_images/formula-1.png ",
                            description=" Important formula. ",
                        ),
                        TopicAsset(
                            page=2,
                            type="formula",
                            path="formula_images/formula-1.png",
                            description="Important formula.",
                        ),
                    ],
                )
            ]

            write_topic_index(output_dir, topics, step_number=1)

            index_data = json.loads((output_dir / "topic_index.json").read_text())
            self.assertEqual(
                index_data,
                [
                    {
                        "topic": "Updated",
                        "pages": [1, 3],
                        "description": "Updated description.",
                        "assets": [
                            {
                                "page": 2,
                                "type": "formula",
                                "path": "formula_images/formula-1.png",
                                "description": "Important formula.",
                            }
                        ],
                    }
                ],
            )
            self.assertNotIn("keywords", index_data[0])
            self.assertFalse((output_dir / "backups").exists())

    def test_write_topic_index_creates_backup_only_when_diagnostics_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            write_topic_index(
                output_dir,
                [
                    TopicEntry(
                        topic="Original",
                        pages=[1],
                        description="Original description.",
                        assets=[],
                    )
                ],
                step_number=1,
                write_backup=True,
            )
            write_topic_index(
                output_dir,
                [
                    TopicEntry(
                        topic="Updated",
                        pages=[1, 2],
                        description="Updated description.",
                        assets=[],
                    )
                ],
                step_number=2,
                write_backup=True,
            )

            backup_data = json.loads(
                (
                    output_dir
                    / "backups"
                    / "topic_index_before_step_0002.json"
                ).read_text()
            )
            self.assertEqual(backup_data[0]["topic"], "Original")

    def test_load_processing_state_resumes_legacy_state_without_window_config(self):
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
            )

            self.assertEqual(state.next_start_page, 4)
            self.assertEqual(state.status, "in_progress")

    def test_write_processing_state_omits_dead_window_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            state_path = write_processing_state(
                output_dir,
                ProcessingState(
                    document_id="doc-1",
                    last_completed_page=2,
                    next_start_page=3,
                    status="in_progress",
                ),
            )

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["next_start_page"], 3)
            self.assertNotIn("main_window_size", payload)
            self.assertNotIn("context_window_size", payload)


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

        self.assertIn("payload", prompt_text)
        self.assertIn("index only the target page", prompt_text.lower())
        self.assertIn("never include previous or next page numbers", prompt_text.lower())
        self.assertIn("reuse the same topic name", prompt_text.lower())
        self.assertIn("do not return keywords", prompt_text.lower())
        self.assertNotIn("Transformer", prompt_text)
        self.assertNotIn("scaled dot-product", prompt_text.lower())
        self.assertNotIn("Attention(Q,K,V)", prompt_text)

    def test_extraction_payload_excludes_full_existing_index(self):
        target_page = PageMarkdown(page=3, markdown="Current target page text.")
        next_page = PageMarkdown(page=4, markdown="Next page boundary text.")
        previous_page_topics = [
            TopicEntry(
                topic="Previous continuing topic",
                pages=[1, 2],
                description="Previous page topic description.",
                assets=[
                    TopicAsset(
                        page=2,
                        type="table",
                        path="table_images/old-table.png",
                        description="Old table from previous page.",
                    )
                ],
            )
        ]
        unrelated_index_topic = TopicEntry(
            topic="Unrelated whole-index topic",
            pages=[99],
            description="This must never be sent to extraction.",
            assets=[],
        )

        payload = json.loads(
            build_extraction_payload(
                target_page=target_page,
                target_page_assets=[
                    TopicAsset(
                        page=3,
                        type="figure",
                        path="image_png_images/current-figure.png",
                        description="Current target page figure.",
                    )
                ],
                previous_page_topics=previous_page_topics,
                next_page=next_page,
            )
        )
        payload_text = json.dumps(payload)

        self.assertEqual(payload["target_page_markdown"], "Current target page text.")
        self.assertEqual(payload["next_page_markdown"], "Next page boundary text.")
        self.assertEqual(
            payload["previous_page_topics"],
            [
                {
                    "topic": "Previous continuing topic",
                    "description": "Previous page topic description.",
                }
            ],
        )
        self.assertIn("current-figure.png", payload_text)
        self.assertNotIn("old-table.png", payload_text)
        self.assertNotIn("pages", payload["previous_page_topics"][0])
        self.assertNotIn(unrelated_index_topic.topic, payload_text)

    def test_matching_payload_contains_only_slots_topics_and_descriptions(self):
        candidates = [
            TopicCandidate(
                topic="Candidate A",
                pages=[3],
                description="Candidate A description.",
                assets=[
                    TopicAsset(
                        page=3,
                        type="formula",
                        path="formula_images/formula-1.png",
                        description="Candidate asset.",
                    )
                ],
            )
        ]
        existing_topics = [
            TopicEntry(
                topic="Existing A",
                pages=[1, 2],
                description="Existing A description.",
                assets=[
                    TopicAsset(
                        page=2,
                        type="table",
                        path="table_images/table-1.png",
                        description="Existing asset.",
                    )
                ],
            )
        ]

        payload = json.loads(
            build_matching_payload(candidates=candidates, existing_topics=existing_topics)
        )
        payload_text = json.dumps(payload)

        self.assertEqual(
            payload,
            {
                "candidates": [
                    {
                        "slot": 0,
                        "topic": "Candidate A",
                        "description": "Candidate A description.",
                    }
                ],
                "existing_topics": [
                    {
                        "slot": 0,
                        "topic": "Existing A",
                        "description": "Existing A description.",
                    }
                ],
            },
        )
        self.assertNotIn("pages", payload_text)
        self.assertNotIn("assets", payload_text)
        self.assertNotIn("formula_images", payload_text)
        self.assertNotIn("table_images", payload_text)

    def test_matching_prompt_uses_slot_targets_without_asset_or_page_proximity(self):
        prompt_text = str(TOPIC_MATCHING_PROMPT).lower()

        self.assertIn("matched_batch_slot", prompt_text)
        self.assertIn("no_match", prompt_text)
        self.assertIn("slot", prompt_text)
        self.assertNotIn("asset-backed", prompt_text)
        self.assertNotIn("page proximity", prompt_text)
        self.assertNotIn("assets", prompt_text)


class DocumentIndexingBackwardBatchMatchingTests(unittest.TestCase):
    def run_update(self, current_index, candidates, client, batch_size=2):
        with tempfile.TemporaryDirectory() as temp_dir:
            return update_topic_index(
                current_index=current_index,
                candidates=candidates,
                client=client,
                output_dir=Path(temp_dir),
                document_id="doc-1",
                processing_state=ProcessingState(
                    document_id="doc-1",
                    last_completed_page=3,
                    next_start_page=4,
                    status="in_progress",
                ),
                event_callback=None,
                target_page=4,
                total_pages=4,
                topic_match_batch_size=batch_size,
            )

    def test_all_candidates_resolved_in_first_tail_batch_stops_early(self):
        current_index = [
            make_topic("Older topic", 1),
            make_topic("Tail target", 2),
            make_topic("Newer unrelated", 3),
        ]
        candidates = [
            make_candidate(
                "Tail target",
                page=4,
                assets=[make_asset(page=4, path="table_images/current.png")],
            )
        ]

        def respond(call_number, batch_candidates, batch_topics):
            self.assertEqual(call_number, 1)
            self.assertEqual(
                [topic.topic for topic in batch_topics],
                ["Tail target", "Newer unrelated"],
            )
            return [update_decision(candidate_slot=0, matched_slot=0)]

        client = BatchMatchingClient(respond)

        updated_index, added, updated = self.run_update(
            current_index,
            candidates,
            client,
            batch_size=2,
        )

        self.assertEqual(len(client.match_calls), 1)
        self.assertEqual(added, [])
        self.assertEqual(updated, ["Tail target"])
        self.assertEqual(
            [topic.topic for topic in updated_index],
            ["Older topic", "Newer unrelated", "Tail target"],
        )
        self.assertEqual(updated_index[-1].pages, [2, 4])
        self.assertEqual(
            [asset.path for asset in updated_index[-1].assets],
            ["table_images/current.png"],
        )

    def test_partial_first_batch_resolution_carries_only_unresolved_backward(self):
        current_index = [
            make_topic("Older unrelated", 1),
            make_topic("Older target", 1),
            make_topic("Newer unrelated", 2),
            make_topic("Tail target", 3),
        ]
        candidates = [
            make_candidate("Tail target", page=4),
            make_candidate("Older target", page=4),
        ]

        def respond(call_number, batch_candidates, batch_topics):
            if call_number == 1:
                self.assertEqual(
                    [candidate.topic for candidate in batch_candidates],
                    ["Tail target", "Older target"],
                )
                self.assertEqual(
                    [topic.topic for topic in batch_topics],
                    ["Newer unrelated", "Tail target"],
                )
                return [
                    update_decision(candidate_slot=0, matched_slot=1),
                    no_match_decision(candidate_slot=1),
                ]

            self.assertEqual(call_number, 2)
            self.assertEqual(
                [candidate.topic for candidate in batch_candidates],
                ["Older target"],
            )
            self.assertEqual(
                [topic.topic for topic in batch_topics],
                ["Older unrelated", "Older target"],
            )
            return [update_decision(candidate_slot=0, matched_slot=1)]

        client = BatchMatchingClient(respond)

        updated_index, added, updated = self.run_update(
            current_index,
            candidates,
            client,
            batch_size=2,
        )

        self.assertEqual(len(client.match_calls), 2)
        self.assertEqual(added, [])
        self.assertEqual(updated, ["Tail target", "Older target"])
        self.assertEqual(
            [topic.topic for topic in updated_index],
            ["Older unrelated", "Newer unrelated", "Tail target", "Older target"],
        )

    def test_unmatched_candidates_after_all_batches_are_added_at_tail(self):
        current_index = [
            make_topic("Old 1", 1),
            make_topic("Old 2", 2),
            make_topic("Old 3", 3),
        ]
        candidates = [make_candidate("Never matched", page=4)]

        def respond(call_number, batch_candidates, batch_topics):
            return [no_match_decision(candidate_slot=0)]

        client = BatchMatchingClient(respond)

        updated_index, added, updated = self.run_update(
            current_index,
            candidates,
            client,
            batch_size=2,
        )

        self.assertEqual(len(client.match_calls), 2)
        self.assertEqual(added, ["Never matched"])
        self.assertEqual(updated, [])
        self.assertEqual(updated_index[-1].topic, "Never matched")
        self.assertEqual(updated_index[-1].pages, [4])

    def test_updated_old_topic_moves_to_tail(self):
        current_index = [
            make_topic("Old target", 1),
            make_topic("Middle topic", 2),
            make_topic("Tail topic", 3),
        ]
        candidates = [make_candidate("Old target", page=4)]

        def respond(call_number, batch_candidates, batch_topics):
            self.assertEqual(
                [topic.topic for topic in batch_topics],
                ["Old target", "Middle topic", "Tail topic"],
            )
            return [update_decision(candidate_slot=0, matched_slot=0)]

        client = BatchMatchingClient(respond)

        updated_index, added, updated = self.run_update(
            current_index,
            candidates,
            client,
            batch_size=10,
        )

        self.assertEqual(added, [])
        self.assertEqual(updated, ["Old target"])
        self.assertEqual(
            [topic.topic for topic in updated_index],
            ["Middle topic", "Tail topic", "Old target"],
        )

    def test_batch_matcher_payload_contains_no_assets_or_pages(self):
        current_index = [
            make_topic(
                "Asset-heavy old topic",
                1,
                assets=[make_asset(page=1, path="table_images/old.png")],
            )
        ]
        candidates = [
            make_candidate(
                "Asset-heavy candidate",
                page=4,
                assets=[make_asset(page=4, path="table_images/new.png")],
            )
        ]

        def respond(call_number, batch_candidates, batch_topics):
            return [no_match_decision(candidate_slot=0)]

        client = BatchMatchingClient(respond)

        self.run_update(current_index, candidates, client, batch_size=10)

        payload_text = json.dumps(client.match_payloads)
        self.assertEqual(
            client.match_payloads[0],
            {
                "candidates": [
                    {
                        "slot": 0,
                        "topic": "Asset-heavy candidate",
                        "description": "Asset-heavy candidate candidate description.",
                    }
                ],
                "existing_topics": [
                    {
                        "slot": 0,
                        "topic": "Asset-heavy old topic",
                        "description": "Asset-heavy old topic description.",
                    }
                ],
            },
        )
        self.assertNotIn("pages", payload_text)
        self.assertNotIn("assets", payload_text)
        self.assertNotIn("table_images", payload_text)


class DocumentIndexingPipelineTests(unittest.TestCase):
    def test_document_indexing_uses_sequential_pipeline_without_langgraph_imports(self):
        indexing_dir = Path("src/document_indexing")
        python_files = [
            path
            for path in indexing_dir.glob("*.py")
            if path.name != "__pycache__"
        ]
        combined_source = "\n".join(
            path.read_text(encoding="utf-8") for path in python_files
        )

        self.assertTrue((indexing_dir / "pipeline.py").exists())
        self.assertTrue((indexing_dir / "steps.py").exists())
        self.assertNotIn("langgraph", combined_source.lower())
        self.assertNotIn("StateGraph", combined_source)
        self.assertNotIn("export_graph_mermaid", combined_source)

    def test_pipeline_indexes_adjacent_target_pages_into_one_continuous_topic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pages_dir = root / "pages_md"
            output_dir = root / "indexing_output"
            events = []
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
                original_filename="capital.pdf",
                include_next_page_context=True,
                client=FakeIndexingClient(),
                event_callback=lambda *args: events.append(args),
            )

            topic_index = json.loads(output.topic_index_path.read_text())
            processing_state = json.loads(output.processing_state_path.read_text())
            agent_guide = output.agent_md_path.read_text(encoding="utf-8")

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
            self.assertNotIn("main_window_size", processing_state)
            self.assertNotIn("context_window_size", processing_state)
            log_text = output.revision_log_path.read_text(encoding="utf-8")
            self.assertIn("Target page: 1", log_text)
            self.assertIn("Added topics:", log_text)
            self.assertIn("Updated topics:", log_text)
            self.assertIn("reason:", log_text)
            self.assertFalse(output.validation_report_path.exists())
            self.assertFalse((output_dir / "backups").exists())
            self.assertTrue(output.agent_md_path.exists())
            self.assertIn("- document_id: capital-doc", agent_guide)
            self.assertIn("- filename: capital.pdf", agent_guide)
            self.assertIn("- total pages: 3", agent_guide)
            self.assertIn("Read `indexing_output/topic_index.json` first.", agent_guide)
            self.assertIn("Do not read the whole document by default.", agent_guide)
            self.assertIn(
                ("document_indexing", "indexing_page", "Indexing page 1 of 3", 1, 3),
                events,
            )
            self.assertIn(
                ("document_indexing", "indexing_page", "Indexing page 3 of 3", 3, 3),
                events,
            )

    def test_diagnostics_mode_writes_revision_log_validation_report_and_backups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pages_dir = root / "pages_md"
            output_dir = root / "indexing_output"
            pages_dir.mkdir()
            for page_no in range(1, 3):
                (pages_dir / f"page_{page_no:04d}.md").write_text(
                    f"Neutral policy content on page {page_no}.",
                    encoding="utf-8",
                )

            output = run_document_indexing(
                pages_folder_path=pages_dir,
                output_folder_path=output_dir,
                document_id="capital-doc",
                include_next_page_context=True,
                write_diagnostics=True,
                client=FakeIndexingClient(),
            )

            log_text = output.revision_log_path.read_text(encoding="utf-8")
            report = json.loads(output.validation_report_path.read_text(encoding="utf-8"))

            self.assertIn("Target page: 1", log_text)
            self.assertIn("Target page: 2", log_text)
            self.assertIn("Estimated topic index size:", log_text)
            self.assertEqual(report["status"], "passed")
            self.assertGreater(report["estimated_tokens"], 0)
            self.assertEqual(report["warnings"], [])
            self.assertTrue(
                (
                    output_dir
                    / "backups"
                    / "topic_index_before_step_0002.json"
                ).exists()
            )

    def test_indexing_retries_transient_llm_errors_and_emits_waiting_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pages_dir = root / "pages_md"
            output_dir = root / "indexing_output"
            events = []
            pages_dir.mkdir()
            (pages_dir / "page_0001.md").write_text(
                "Neutral policy content on page 1.",
                encoding="utf-8",
            )
            client = FlakyExtractIndexingClient()

            with patch("backend.services.retry_utils.time.sleep", return_value=None):
                output = run_document_indexing(
                    pages_folder_path=pages_dir,
                    output_folder_path=output_dir,
                    document_id="capital-doc",
                    include_next_page_context=True,
                    client=client,
                    event_callback=lambda *args: events.append(args),
                )

            processing_state = json.loads(output.processing_state_path.read_text())

        self.assertEqual(client.extract_attempts, 2)
        self.assertEqual(processing_state["status"], "completed")
        self.assertTrue(any(event[1] == "waiting_for_llm" for event in events))
        self.assertTrue(any(event[1] == "retry" for event in events))


if __name__ == "__main__":
    unittest.main()
