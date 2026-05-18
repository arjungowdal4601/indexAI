# Document Processing Pipeline

This project has two separate runnable pipelines.

The document processing pipeline runs:

1. **Docling conversion**: PDF to raw page-wise markdown and visual assets.
2. **Table continuity detection**: deterministic multi-page table grouping.
3. **Enrichment**: readable markdown with table, figure, and formula images plus descriptions.
Topic indexing is a separate pipeline that reads the enriched page Markdown and writes a compact topic-centric JSON index.

No LLM is used during Docling conversion or table-continuity detection. Enrichment and topic indexing use LangChain chat prompt templates and `langchain-openai`; indexing uses schema-based structured output.

## Structure

```text
doc_comparing/
|-- main.py
|-- README.md
|-- requirements.txt
|-- .env
|-- .gitignore
|-- sample.pdf
|-- src/
|   |-- doc_processing/
|   |   |-- __init__.py
|   |   |-- config.py
|   |   |-- pipeline.py
|   |   |-- docling_converter.py
|   |   |-- table_detection.py
|   |   |-- enrichment.py
|   |   `-- prompts.py
|   `-- document_indexing/
|       |-- __init__.py
|       |-- __main__.py
|       |-- config.py
|       |-- graph.py
|       |-- llm.py
|       |-- main.py
|       |-- prompts.py
|       |-- schemas.py
|       |-- storage.py
|       `-- validator.py
|-- tests/
|   |-- conftest.py
|   |-- test_docling_converter_contract.py
|   |-- test_document_indexing.py
|   |-- test_enrichment.py
|   |-- test_pipeline.py
|   |-- test_prompts.py
|   `-- test_table_detection_output.py
`-- sample_doc_assets/
    |-- docling_assets/
    |-- enriched_doc/
    `-- indexing_output/
```

## Run Document Processing

1. Put the source PDF in the project root.
2. Update `PDF_PATH` in `src/doc_processing/config.py` if the file is not `sample.pdf`.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Set `OPENAI_API_KEY` in `.env`.
5. Run:

```bash
python main.py
```

This runs PDF conversion, table continuity detection, and enrichment only. It does not run the document indexing pipeline.

## Run Document Indexing

Run indexing separately after enriched page Markdown exists:

```bash
python src/document_indexing/main.py
```

By default this reads:

```text
sample_doc_assets/enriched_doc/pages_md/
```

and writes:

```text
sample_doc_assets/indexing_output/topic_index.json
```

You can override paths:

```bash
python src/document_indexing/main.py --pages-folder sample_doc_assets/enriched_doc/pages_md --output-folder sample_doc_assets/indexing_output --document-id sample
```

## Outputs

For `sample.pdf`, generated artifacts are written under `sample_doc_assets/`:

```text
sample_doc_assets/
|-- docling_assets/
|   |-- pages_md/
|   |-- page_images/
|   |-- image_png_images/
|   |-- table_images/
|   |-- formula_images/
|   |-- stitched_raw_docling_markdown.md
|   `-- table_continuity_map.json
|-- enriched_doc/
|   |-- pages_md/
|   |-- image_png_images/
|   |-- table_images/
|   |-- formula_images/
|   `-- readable_processed_doc.md
`-- indexing_output/
    |-- topic_index.json
    |-- processing_state.json
    |-- validation_report.json
    |-- revision_log.md
    `-- backups/
```

The readable markdown keeps old-style relative image links such as `![Table](table_images/table-1.png)` while using table-continuity context to improve continued table descriptions.

The topic index is a single continuous JSON list grouped only by topic. Page windows are internal to indexing and are not written into `topic_index.json`.
