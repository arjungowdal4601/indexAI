import inspect
import unittest

import doc_processing.enrichment as enrichment
from doc_processing.prompts import (
    FORMULA_PROMPT,
    FORMULA_SYSTEM_PROMPT,
    PICTURE_PROMPT,
    PICTURE_SYSTEM_PROMPT,
    TABLE_SYSTEM_PROMPT,
    build_table_context,
    build_table_prompt,
)


class PromptTemplateTests(unittest.TestCase):
    def test_prompts_keep_previous_doc_processor_intent(self):
        self.assertIn(
            "write detailed, retrieval-friendly descriptions of figures",
            PICTURE_SYSTEM_PROMPT,
        )
        self.assertIn(
            "convert table fragments from technical PDFs into detailed, retrieval-friendly prose",
            TABLE_SYSTEM_PROMPT,
        )
        self.assertIn(
            'Start with one line beginning exactly with "LaTeX:"',
            FORMULA_SYSTEM_PROMPT,
        )

    def test_prompt_templates_return_langchain_messages_with_images(self):
        self.assertEqual(PICTURE_PROMPT.__class__.__name__, "ChatPromptTemplate")
        self.assertEqual(FORMULA_PROMPT.__class__.__name__, "ChatPromptTemplate")
        self.assertEqual(
            build_table_prompt(True, True).__class__.__name__,
            "ChatPromptTemplate",
        )

        picture_messages = PICTURE_PROMPT.invoke({"image_base64": "pic"}).to_messages()
        self.assertEqual(picture_messages[0].type, "system")
        self.assertEqual(picture_messages[1].type, "human")
        self.assertEqual(picture_messages[1].content[1]["type"], "image")
        self.assertEqual(picture_messages[1].content[1]["mime_type"], "image/png")

        table_context = build_table_context(
            table_id="table_001",
            page_no=2,
            pages=[2, 3],
            current_markdown="| A | B |",
            previous_markdown="| A | B old |",
        )
        table_messages = build_table_prompt(True, True).invoke(
            {
                "table_context": table_context,
                "current_image_base64": "current",
                "previous_image_base64": "previous",
            }
        ).to_messages()
        table_text = table_messages[1].content[0]["text"]
        table_system = table_messages[0].content

        self.assertEqual(table_messages[0].type, "system")
        self.assertIn("Previous table fragment markdown", table_text)
        self.assertIn(
            "Describe the current fragment only. Keep exact visible terms, units, IDs, and numeric values.",
            table_text,
        )
        self.assertNotIn("Return bullet points", table_text)
        self.assertNotIn("Return bullet points", table_system)
        self.assertEqual(table_messages[1].content[2]["type"], "image")
        self.assertEqual(table_messages[1].content[4]["type"], "image")

        formula_messages = FORMULA_PROMPT.invoke(
            {
                "image_base64": "formula",
                "formula_markdown": "$$E = mc^2$$",
            }
        ).to_messages()
        self.assertEqual(formula_messages[0].type, "system")
        self.assertIn(
            "Parser extracted LaTeX or markdown: $$E = mc^2$$",
            formula_messages[1].content[0]["text"],
        )
        self.assertEqual(formula_messages[1].content[1]["type"], "image")

    def test_enrichment_client_uses_prompt_module_not_inline_messages(self):
        source = inspect.getsource(enrichment.OpenAIEnrichmentClient)
        self.assertIn("build_table_prompt", source)
        self.assertIn("PICTURE_PROMPT", source)
        self.assertIn("FORMULA_PROMPT", source)
        self.assertIn("| self.llm", source)
        self.assertNotIn("SystemMessage", source)
        self.assertNotIn("HumanMessage", source)
        self.assertNotIn("not text.lower().startswith", source)
        self.assertNotIn("from openai", inspect.getsource(enrichment))


if __name__ == "__main__":
    unittest.main()
