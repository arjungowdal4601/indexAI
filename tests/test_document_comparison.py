import inspect
import json
import tempfile
import unittest
from pathlib import Path

from document_comparison.graph import export_graph_mermaid, run_document_comparison
from document_comparison.llm import LangChainComparisonClient
from document_comparison.nodes import validate_comparison_plan_node
from document_comparison.prompts import (
    COMPARISON_PLAN_PROMPT,
    COMPRESS_REGULATORY_EVIDENCE_PROMPT,
    GAP_ANALYSIS_PROMPT,
)
from document_comparison.schemas import (
    ComparisonPlan,
    ComparisonPlanItem,
    DocumentManifest,
    GapFinding,
    PageContext,
    RegulatoryEvidenceSummary,
    RegulatoryTopicMapping,
    TopicAsset,
    TopicEntry,
)
from document_comparison.storage import (
    load_document_manifest,
    load_topic_index,
    read_sop_page_window,
)


class FakeComparisonClient:
    def __init__(self, status="compliant", severity="informational"):
        self.status = status
        self.severity = severity
        self.planned_pages = []
        self.compressed_pages = []
        self.gap_modes = []

    def plan_sop_page_comparison(
        self,
        sop_target_page,
        sop_next_page,
        previous_sop_page_summary,
        regulatory_topic_index_json,
    ):
        self.planned_pages.append(sop_target_page.page)
        topics = json.loads(regulatory_topic_index_json)
        topic = topics[0]
        return ComparisonPlan(
            sop_page=sop_target_page.page,
            plan_items=[
                ComparisonPlanItem(
                    sop_topic=f"Procedure topic page {sop_target_page.page}",
                    sop_page=sop_target_page.page,
                    sop_claim_or_requirement="Operators perform a controlled step.",
                    sop_evidence_excerpt="Operators shall perform the controlled step.",
                    regulatory_mappings=[
                        RegulatoryTopicMapping(
                            regulatory_topic=topic["topic"],
                            regulatory_pages=topic["pages"],
                            reason="The topic covers controlled procedural steps.",
                            confidence="high",
                        )
                    ],
                    comparison_focus="Check required roles, records, and timing.",
                )
            ],
            page_summary=f"SOP page {sop_target_page.page} describes a controlled step.",
            planning_notes_for_trace="Mapped the SOP step to the regulatory topic.",
        )

    def compress_regulatory_evidence(self, plan_item, regulatory_page_context):
        self.compressed_pages.append(regulatory_page_context.page)
        return RegulatoryEvidenceSummary(
            regulatory_page=regulatory_page_context.page,
            regulatory_topic=plan_item.regulatory_mappings[0].regulatory_topic,
            useful=True,
            evidence="Compressed regulatory evidence for the controlled step.",
            obligations=["Document the role and timing."],
            source_excerpt="The regulation requires documented role and timing.",
        )

    def execute_gap_analysis(
        self,
        plan_item,
        regulatory_evidence,
        comparison_memory_mode,
    ):
        self.gap_modes.append(comparison_memory_mode)
        return GapFinding(
            sop_page=plan_item.sop_page,
            sop_topic=plan_item.sop_topic,
            regulatory_topics=[
                mapping.regulatory_topic for mapping in plan_item.regulatory_mappings
            ],
            regulatory_pages_used=sorted(
                {
                    page
                    for mapping in plan_item.regulatory_mappings
                    for page in mapping.regulatory_pages
                }
            ),
            status=self.status,
            severity=self.severity,
            confidence="high",
            sop_evidence=plan_item.sop_evidence_excerpt,
            regulatory_evidence=regulatory_evidence[:300],
            gap_explanation="The SOP evidence was compared against regulatory evidence.",
            recommended_action="No action required.",
            missing_or_weak_elements=[],
        )


def write_page(folder: Path, page: int, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"page_{page:04d}.md").write_text(text, encoding="utf-8")


def make_document_root(
    base: Path,
    role: str,
    doc_id: str,
    total_pages: int,
    topic_index: list[dict] | None = None,
    manifest_name: str = "document_manifest.json",
) -> Path:
    root = base / "processed_documents" / role / doc_id
    pages = root / "enriched_doc" / "pages_md"
    images = root / "docling_assets" / "page_images"
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)
    (source / f"{doc_id}.pdf").write_text("placeholder", encoding="utf-8")
    for page in range(1, total_pages + 1):
        write_page(pages, page, f"--- PAGE {page} ---\n{role} page {page} evidence.")

    manifest = {
        "document_id": doc_id,
        "role": role,
        "source_file": f"source/{doc_id}.pdf",
        "enriched_pages_folder": "enriched_doc/pages_md",
        "page_images_folder": "docling_assets/page_images",
        "total_pages": total_pages,
    }
    if topic_index is not None:
        index_path = root / "indexing_output" / "topic_index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(topic_index), encoding="utf-8")
        manifest["topic_index_path"] = "indexing_output/topic_index.json"

    (root / manifest_name).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return root


def regulatory_topics(pages=None):
    pages = pages or [1]
    return [
        {
            "topic": "Controlled procedural steps",
            "pages": pages,
            "description": "Requires documented roles, records, timing, and controls.",
            "assets": [
                {
                    "page": pages[0],
                    "type": "table",
                    "path": "table_images/table-1.png",
                    "description": "Table listing required procedural controls.",
                }
            ],
        }
    ]


class DocumentComparisonStorageTests(unittest.TestCase):
    def test_load_document_manifest_resolves_relative_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_document_root(
                Path(temp_dir),
                "regulatory",
                "reg_v1",
                total_pages=1,
                topic_index=regulatory_topics(),
            )

            manifest = load_document_manifest(root)

            self.assertEqual(
                manifest,
                DocumentManifest(
                    document_id="reg_v1",
                    role="regulatory",
                    root_path=root,
                    source_file=root / "source" / "reg_v1.pdf",
                    enriched_pages_folder=root / "enriched_doc" / "pages_md",
                    page_images_folder=root / "docling_assets" / "page_images",
                    total_pages=1,
                    topic_index_path=root / "indexing_output" / "topic_index.json",
                ),
            )

    def test_read_sop_page_window_reads_target_and_next_page_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_document_root(Path(temp_dir), "sop", "sop_v1", total_pages=3)
            manifest = load_document_manifest(root)

            target, next_page = read_sop_page_window(manifest, target_page=2)

            self.assertEqual(target.page, 2)
            self.assertEqual(next_page.page, 3)
            self.assertIn("sop page 2 evidence", target.markdown)
            self.assertIn("sop page 3 evidence", next_page.markdown)
            self.assertNotIn("sop page 1 evidence", target.markdown + next_page.markdown)

    def test_load_document_manifest_accepts_canonical_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_document_root(
                Path(temp_dir),
                "regulatory",
                "reg_v1",
                total_pages=1,
                topic_index=regulatory_topics(),
                manifest_name="manifest.json",
            )
            legacy_manifest = root / "document_manifest.json"
            if legacy_manifest.exists():
                legacy_manifest.unlink()
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["document_type"] = manifest.pop("role")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            loaded = load_document_manifest(root)

            self.assertEqual(loaded.document_id, "reg_v1")
            self.assertEqual(loaded.role, "regulatory")
            self.assertEqual(
                loaded.topic_index_path,
                root / "indexing_output" / "topic_index.json",
            )

    def test_load_topic_index_reads_assets_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_document_root(
                Path(temp_dir),
                "regulatory",
                "reg_v1",
                total_pages=1,
                topic_index=regulatory_topics(),
            )
            manifest = load_document_manifest(root)

            topics = load_topic_index(manifest.topic_index_path)

            self.assertEqual(
                topics[0],
                TopicEntry(
                    topic="Controlled procedural steps",
                    pages=[1],
                    description="Requires documented roles, records, timing, and controls.",
                    assets=[
                        TopicAsset(
                            page=1,
                            type="table",
                            path="table_images/table-1.png",
                            description="Table listing required procedural controls.",
                        )
                    ],
                ),
            )


class DocumentComparisonGraphTests(unittest.TestCase):
    def test_validate_plan_rejects_nonexistent_regulatory_pages(self):
        plan = ComparisonPlan(
            sop_page=1,
            plan_items=[
                ComparisonPlanItem(
                    sop_topic="Procedure topic",
                    sop_page=1,
                    sop_claim_or_requirement="Claim",
                    sop_evidence_excerpt="Evidence",
                    regulatory_mappings=[
                        RegulatoryTopicMapping(
                            regulatory_topic="Controlled procedural steps",
                            regulatory_pages=[99],
                            reason="Bad page.",
                            confidence="high",
                        )
                    ],
                    comparison_focus="Focus",
                )
            ],
            page_summary="Summary",
            planning_notes_for_trace="Trace",
        )

        with self.assertRaisesRegex(ValueError, "not in topic index"):
            validate_comparison_plan_node(
                {
                    "comparison_plan": plan,
                    "current_sop_page": 1,
                    "regulatory_topic_index": [
                        TopicEntry(
                            topic="Controlled procedural steps",
                            pages=[1],
                            description="Valid topic.",
                            assets=[],
                        )
                    ],
                }
            )

    def test_validate_plan_repairs_paraphrased_topic_when_pages_match_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            pages = base / "pages_md"
            for page in [21, 22, 27]:
                write_page(pages, page, f"Regulatory page {page} evidence.")

            canonical_topic = "CGMP data integrity principles and controlled record lifecycle"
            plan = ComparisonPlan(
                sop_page=2,
                plan_items=[
                    ComparisonPlanItem(
                        sop_topic="Role evidence table",
                        sop_page=2,
                        sop_claim_or_requirement="The SOP cites logs and spreadsheets.",
                        sop_evidence_excerpt="Shift log, email, and spreadsheet evidence.",
                        regulatory_mappings=[
                            RegulatoryTopicMapping(
                                regulatory_topic="Controlled record lifecycle and data integrity principles",
                                regulatory_pages=[21, 22, 27],
                                reason="The pages cover data integrity and controlled records.",
                                confidence="medium",
                            )
                        ],
                        comparison_focus="Check controlled records and traceability.",
                    )
                ],
                page_summary="SOP page 2 includes evidence artifacts.",
                planning_notes_for_trace="Planner paraphrased the indexed topic.",
            )

            validate_comparison_plan_node(
                {
                    "comparison_plan": plan,
                    "current_sop_page": 2,
                    "regulatory_topic_index": [
                        TopicEntry(
                            topic=canonical_topic,
                            pages=[21, 22, 27],
                            description="Controls CGMP data integrity and the controlled record lifecycle.",
                            assets=[],
                        )
                    ],
                    "regulatory_manifest": DocumentManifest(
                        document_id="reg_v1",
                        role="regulatory",
                        root_path=base,
                        source_file=base / "source.pdf",
                        enriched_pages_folder=pages,
                        page_images_folder=base / "page_images",
                        total_pages=27,
                        topic_index_path=base / "topic_index.json",
                    ),
                }
            )

            self.assertEqual(
                plan.plan_items[0].regulatory_mappings[0].regulatory_topic,
                canonical_topic,
            )

    def test_direct_gap_analysis_path_writes_page_and_final_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            reg_root = make_document_root(
                base,
                "regulatory",
                "reg_v1",
                total_pages=1,
                topic_index=regulatory_topics(),
            )
            sop_root = make_document_root(base, "sop", "sop_v1", total_pages=1)
            run_dir = base / "comparison_runs" / "run_direct"
            client = FakeComparisonClient(status="compliant", severity="informational")

            output = run_document_comparison(
                regulatory_root=reg_root,
                sop_root=sop_root,
                comparison_run_dir=run_dir,
                comparison_run_id="run_direct",
                client=client,
                end_page=1,
            )

            self.assertEqual(client.gap_modes, ["direct"])
            self.assertTrue((run_dir / "item_results" / "sop_page_0001_item_001.json").exists())
            self.assertTrue((run_dir / "page_reports" / "sop_page_0001.json").exists())
            self.assertTrue((run_dir / "final_report.csv").exists())
            report = json.loads(output.gap_report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["compliant"], 1)
            self.assertEqual(report["counts"]["total_findings"], 1)

    def test_compressed_gap_analysis_path_writes_compressed_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            reg_root = make_document_root(
                base,
                "regulatory",
                "reg_v1",
                total_pages=2,
                topic_index=regulatory_topics(pages=[1, 2]),
            )
            sop_root = make_document_root(base, "sop", "sop_v1", total_pages=1)
            run_dir = base / "comparison_runs" / "run_compressed"
            client = FakeComparisonClient(status="partially_compliant", severity="major")

            run_document_comparison(
                regulatory_root=reg_root,
                sop_root=sop_root,
                comparison_run_dir=run_dir,
                comparison_run_id="run_compressed",
                client=client,
                end_page=1,
                max_direct_regulatory_pages=1,
            )

            self.assertEqual(client.gap_modes, ["compressed"])
            self.assertEqual(client.compressed_pages, [1, 2])
            self.assertTrue(
                (
                    run_dir
                    / "evidence"
                    / "sop_page_0001"
                    / "compressed_evidence_item_001.json"
                ).exists()
            )

    def test_comparison_run_resumes_from_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            reg_root = make_document_root(
                base,
                "regulatory",
                "reg_v1",
                total_pages=1,
                topic_index=regulatory_topics(),
            )
            sop_root = make_document_root(base, "sop", "sop_v1", total_pages=2)
            run_dir = base / "comparison_runs" / "run_resume"
            state_dir = run_dir / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "comparison_state.json").write_text(
                json.dumps(
                    {
                        "comparison_run_id": "run_resume",
                        "last_completed_sop_page": 1,
                        "current_sop_page": 2,
                        "completed_item_result_paths": [],
                        "completed_page_result_paths": [],
                        "status": "in_progress",
                    }
                ),
                encoding="utf-8",
            )
            client = FakeComparisonClient()

            run_document_comparison(
                regulatory_root=reg_root,
                sop_root=sop_root,
                comparison_run_dir=run_dir,
                comparison_run_id="run_resume",
                client=client,
                start_page=1,
                end_page=2,
                resume=True,
            )

            self.assertEqual(client.planned_pages, [2])
            state = json.loads(
                (state_dir / "comparison_state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["last_completed_sop_page"], 2)
            self.assertEqual(state["status"], "completed")

    def test_graph_exports_mermaid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "comparison_graph.mmd"

            export_graph_mermaid(output_path)

            mermaid = output_path.read_text(encoding="utf-8")
            self.assertIn("plan_sop_page_comparison", mermaid)
            self.assertIn("execute_gap_analysis", mermaid)
            self.assertIn("aggregate_final_gap_report", mermaid)


class DocumentComparisonSourceTests(unittest.TestCase):
    def test_prompts_use_chat_prompt_template(self):
        self.assertIsNotNone(COMPARISON_PLAN_PROMPT)
        self.assertIsNotNone(COMPRESS_REGULATORY_EVIDENCE_PROMPT)
        self.assertIsNotNone(GAP_ANALYSIS_PROMPT)
        source = inspect.getsource(__import__("document_comparison.prompts").prompts)
        self.assertIn("ChatPromptTemplate.from_messages", source)

    def test_llm_uses_langchain_structured_output_not_plain_openai_sdk(self):
        source = inspect.getsource(LangChainComparisonClient)

        self.assertIn("ChatOpenAI", source)
        self.assertIn("with_structured_output(ComparisonPlan", source)
        self.assertIn("with_structured_output(RegulatoryEvidenceSummary", source)
        self.assertIn("with_structured_output(GapFinding", source)
        self.assertNotIn("from openai import", source)
        self.assertNotIn("import openai", source)


if __name__ == "__main__":
    unittest.main()
