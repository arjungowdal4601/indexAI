# Document Processing Pipeline

This project has separate runnable pipelines plus a backend framework wrapper.

The document processing pipeline runs:

1. **Docling conversion**: PDF to raw page-wise markdown and visual assets.
2. **Table continuity detection**: deterministic multi-page table grouping.
3. **Enrichment**: readable markdown with table, figure, and formula images plus descriptions.
Topic indexing is a separate pipeline that reads the enriched page Markdown and writes a compact topic-centric JSON index.
Topic retrieval is a separate query-time pipeline that reads the topic index, loads only selected enriched page Markdown files, and answers from that evidence.

No LLM is used during Docling conversion or table-continuity detection. Enrichment and topic indexing use LangChain chat prompt templates and `langchain-openai`; indexing uses schema-based structured output.
Retrieval also uses LangGraph, LangChain chat prompt templates, and schema-based structured output.

The backend MVP wraps these pipelines with FastAPI, CSV registries, and canonical
`storage/` folders for upload, processing, document indexing, SOP-vs-regulatory
comparison, document co-pilot Q&A, report access, and page-image serving.

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
|   |-- document_indexing/
|       |-- __init__.py
|       |-- __main__.py
|       |-- config.py
|       |-- graph.py
|       |-- llm.py
|       |-- main.py
|       |-- nodes.py
|       |-- prompts.py
|       |-- routers.py
|       |-- schemas.py
|       |-- state.py
|       |-- storage.py
|       `-- validator.py
|   `-- document_retrieval/
|       |-- __init__.py
|       |-- __main__.py
|       |-- config.py
|       |-- graph.py
|       |-- llm.py
|       |-- main.py
|       |-- nodes.py
|       |-- prompts.py
|       |-- routers.py
|       |-- schemas.py
|       |-- state.py
|       `-- storage.py
|-- tests/
|   |-- conftest.py
|   |-- test_docling_converter_contract.py
|   |-- test_document_indexing.py
|   |-- test_document_retrieval.py
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

The topic index is a single continuous JSON list grouped only by topic. Page windows are internal to indexing and are not written into `topic_index.json`. Each topic entry contains `topic`, `pages`, a rich evidence-focused `description`, and `assets` for target-page figures, tables, and formulas. Legacy `keywords` entries can still be loaded, but new index writes use `assets` instead.

## Artifact Retention

Backend artifact cleanup runs automatically after successful document indexing and
successful comparison report generation. Configure the mode in `backend/config.py`:

```python
ARTIFACT_RETENTION_MODE = "standard"
```

Supported modes:

```text
debug     keep everything
standard  default; keep product artifacts only
minimal   keep only essential artifacts
```

In standard mode, prepared backend documents keep this final structure:

```text
storage/documents/<type>/<document_id>/
|-- original/source.pdf
|-- manifest.json
|-- page_images/
|-- enriched_doc/
|   |-- pages_md/
|   |-- image_png_images/
|   |-- table_images/
|   |-- formula_images/
|   `-- readable_processed_doc.md
`-- indexing_output/
    `-- topic_index.json
```

In standard mode, completed comparisons keep this final structure:

```text
storage/comparisons/<comparison_id>/
|-- comparison_request.json
|-- page_reports/
|-- final_report.json
|-- final_report.md
|-- final_report.csv
|-- reports/executive_summary.md
|-- state/
|-- logs/
`-- artifact_cleanup.json
```

## Run Document Retrieval

Run retrieval separately after enriched page Markdown and `topic_index.json` exist:

```bash
python src/document_retrieval/main.py "What is scaled dot-product attention?"
```

or:

```bash
python -m document_retrieval "What is scaled dot-product attention?"
```

By default this reads:

```text
sample_doc_assets/indexing_output/topic_index.json
sample_doc_assets/enriched_doc/pages_md/
```

You can override paths and the retrieval context budget:

```bash
python src/document_retrieval/main.py "What is scaled dot-product attention?" --topic-index sample_doc_assets/indexing_output/topic_index.json --pages-folder sample_doc_assets/enriched_doc/pages_md --max-direct-pages 10 --max-direct-estimated-tokens 70000
```

The retrieval output includes a deterministic retrieval trace, page files read, memory mode, final answer, pages used, and any missing information reported by the model.

## Run Backend MVP

Install dependencies, then start FastAPI from the project root:

```bash
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

Start the Streamlit frontend in a second terminal:

```powershell
$env:DOC_COMPARING_API_BASE_URL = "http://127.0.0.1:8000"
streamlit run frontend/streamlit_app.py
```

Or run both backend and frontend together from the `compute` Conda environment:

```powershell
.\run_comparison_app.ps1
```

The script starts FastAPI on `http://127.0.0.1:8000` and Streamlit on
`http://127.0.0.1:8501`, then stops both services when you press `Ctrl+C`.

In the framework UI, both regulatory and SOP documents follow the same lifecycle:

```text
upload -> index button -> processing -> indexing -> ready
```

The Streamlit Upload and Prepare page uses a single `Index` button. That button
calls `POST /documents/{document_id}/prepare`, and the backend runs processing
and indexing sequentially before marking the document ready. The lower-level
`/process` and `/index` endpoints remain available for API compatibility.

SOP indexing writes a real `indexing_output/topic_index.json` for uniform document
management and Document Co-pilot Q&A. SOP-vs-regulatory comparison still uses only
the regulatory document's topic index for gap-analysis routing; SOP pages are read
directly as page evidence.

The backend uses `storage/` by default. Override it for tests or alternate
workspaces with:

```bash
set DOC_COMPARING_STORAGE_ROOT=C:\path\to\storage
```

Primary endpoints:

```text
POST /documents/upload
GET /documents
POST /documents/{document_id}/prepare
POST /documents/{document_id}/process
POST /documents/{document_id}/index
GET /jobs/{job_id}
GET /jobs/{job_id}/events
POST /documents/{document_id}/copilot/query
POST /comparisons
GET /comparisons/{comparison_id}
GET /comparisons/{comparison_id}/report
GET /comparisons/{comparison_id}/pages/{sop_page_number}
GET /assets/documents/{document_id}/page-image/{page_number}
```

Canonical backend artifacts are written under:

```text
storage/documents/regulatory/<reg_id>/
storage/documents/sop/<sop_id>/
storage/comparisons/<comparison_id>/
storage/registries/
```
