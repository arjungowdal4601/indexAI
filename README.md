# Document Processing Pipeline

This project implements a staged PDF processing pipeline:

1. **Docling conversion**: PDF to raw page-wise markdown and visual assets.
2. **Table continuity detection**: deterministic multi-page table grouping.
3. **Enrichment**: readable markdown with table, figure, and formula images plus descriptions.

No LLM is used during Docling conversion or table-continuity detection. Enrichment uses LangChain chat prompt templates and `langchain-openai`.

## Structure

```text
doc_comparing/
├── main.py
├── README.md
├── requirements.txt
├── .env
├── .gitignore
├── sample.pdf
├── src/
│   └── doc_comparing/
│       ├── __init__.py
│       ├── config.py
│       ├── pipeline.py
│       ├── docling_converter.py
│       ├── table_detection.py
│       ├── enrichment.py
│       └── prompts.py
├── tests/
│   ├── conftest.py
│   ├── test_enrichment.py
│   ├── test_docling_converter_contract.py
│   ├── test_prompts.py
│   └── test_table_detection_output.py
└── sample_doc_assets/
    ├── docling_assets/
    └── enriched_doc/
```

## Run

1. Put the source PDF in the project root.
2. Update `PDF_PATH` in `src/doc_comparing/config.py` if the file is not `sample.pdf`.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Set `OPENAI_API_KEY` in `.env`.
5. Run:

```bash
python main.py
```

## Outputs

For `sample.pdf`, generated artifacts are written under `sample_doc_assets/`:

```text
sample_doc_assets/
├── docling_assets/
│   ├── pages_md/
│   ├── page_images/
│   ├── image_png_images/
│   ├── table_images/
│   ├── formula_images/
│   ├── stitched_raw_docling_markdown.md
│   └── table_continuity_map.json
└── enriched_doc/
    ├── pages_md/
    ├── image_png_images/
    ├── table_images/
    ├── formula_images/
    └── readable_processed_doc.md
```

The readable markdown keeps old-style relative image links such as `![Table](table_images/table-1.png)` while using table-continuity context to improve continued table descriptions.
