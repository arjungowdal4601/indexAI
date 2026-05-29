import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_indexing.schemas import IndexingOutput


class DocumentIndexingRunnerTests(unittest.TestCase):
    def test_runner_uses_document_indexing_defaults_without_doc_processing_pipeline(self):
        from document_indexing.main import run_indexing_pipeline

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_root = Path(temp_dir) / "sample_doc_assets"
            pages_dir = asset_root / "enriched_doc" / "pages_md"
            output_dir = asset_root / "indexing_output"
            pages_dir.mkdir(parents=True)

            expected_output = IndexingOutput(
                topic_index_path=output_dir / "topic_index.json",
                processing_state_path=output_dir / "processing_state.json",
                revision_log_path=output_dir / "revision_log.md",
                validation_report_path=output_dir / "validation_report.json",
            )

            with patch(
                "document_indexing.main.run_document_indexing",
                return_value=expected_output,
            ) as run_document_indexing:
                output = run_indexing_pipeline(pages_folder_path=pages_dir)

            self.assertEqual(output, expected_output)
            run_document_indexing.assert_called_once_with(
                pages_folder_path=pages_dir,
                output_folder_path=output_dir,
                document_id="sample",
                include_next_page_context=True,
                topic_match_batch_size=10,
                write_diagnostics=False,
                event_callback=None,
            )

    def test_cli_uses_boolean_next_page_and_diagnostics_options(self):
        from document_indexing.main import build_parser

        parser = build_parser()
        default_args = parser.parse_args([])
        disabled_args = parser.parse_args(["--no-next-page-context"])
        diagnostics_args = parser.parse_args(["--write-diagnostics"])
        option_strings = {
            option
            for action in parser._actions
            for option in action.option_strings
        }

        self.assertTrue(default_args.include_next_page_context)
        self.assertFalse(default_args.write_diagnostics)
        self.assertFalse(disabled_args.include_next_page_context)
        self.assertTrue(diagnostics_args.write_diagnostics)
        self.assertIn("--no-next-page-context", option_strings)
        self.assertIn("--write-diagnostics", option_strings)
        self.assertIn("--topic-match-batch-size", option_strings)
        self.assertNotIn("--token-limit", option_strings)
        self.assertNotIn("--main-window-size", option_strings)
        self.assertNotIn("--context-window-size", option_strings)


if __name__ == "__main__":
    unittest.main()
