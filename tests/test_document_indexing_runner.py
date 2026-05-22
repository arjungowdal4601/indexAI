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
                main_window_size=1,
                context_window_size=1,
                token_limit=80000,
                event_callback=None,
            )


if __name__ == "__main__":
    unittest.main()
