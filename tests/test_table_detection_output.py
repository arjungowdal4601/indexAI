import unittest

from doc_processing.table_detection import (
    LogicalTableInternal,
    build_minimal_output_payload,
)


class TableDetectionOutputTests(unittest.TestCase):
    def test_payload_omits_verbose_metadata_and_fragments(self):
        logical_tables = [
            LogicalTableInternal(
                table_id="table_001",
                start_page=2,
                end_page=4,
                pages=[2, 3, 4],
                is_multi_page=True,
                fragment_count=3,
                fragments=[
                    {"page": 2, "table_index_on_page": 1, "block_id": "p0002_t01"},
                    {"page": 3, "table_index_on_page": 1, "block_id": "p0003_t01"},
                    {"page": 4, "table_index_on_page": 1, "block_id": "p0004_t01"},
                ],
                confidence=5.75,
            )
        ]

        payload = build_minimal_output_payload(logical_tables)

        self.assertEqual(
            set(payload),
            {"multi_page_table_count", "tables"},
        )
        self.assertEqual(payload["multi_page_table_count"], 1)
        self.assertEqual(
            set(payload["tables"][0]),
            {
                "table_id",
                "is_multi_page",
                "start_page",
                "end_page",
                "pages",
                "confidence",
            },
        )
        self.assertNotIn("source_pdf", payload)
        self.assertNotIn("generated_at", payload)
        self.assertNotIn("uses_llm", payload)
        self.assertNotIn("uses_openai", payload)
        self.assertNotIn("uses_table_name_matching", payload)
        self.assertNotIn("fragments", payload["tables"][0])


if __name__ == "__main__":
    unittest.main()
