# Document Processing Pipeline

This project has separate runnable pipelines plus a backend framework wrapper.

The document processing pipeline runs:

1. **Docling conversion**: PDF to raw page-wise markdown and visual assets.
2. **Enrichment**: readable markdown with table, figure, and formula images plus descriptions.
Topic indexing is a separate pipeline that reads the enriched page Markdown and writes a compact topic-centric JSON index.
Topic retrieval is a separate query-time pipeline that reads the topic index, loads only selected enriched page Markdown files, and answers from that evidence.

No LLM is used during Docling conversion. Enrichment and topic indexing use LangChain chat prompt templates and `langchain-openai`; indexing uses schema-based structured output.
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
|   |   |-- __main__.py
|   |   |-- config.py
|   |   |-- docling_converter.py
|   |   |-- enrichment.py
|   |   |-- main.py
|   |   |-- pipeline.py
|   |   `-- prompts.py
|   |-- document_indexing/
|       |-- __init__.py
|       |-- __main__.py
|       |-- config.py
|       |-- llm.py
|       |-- main.py
|       |-- pipeline.py
|       |-- prompts.py
|       |-- schemas.py
|       |-- steps.py
|       `-- storage.py
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
|   `-- test_prompts.py
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

Package entrypoint, when the package is installed or `src` is on `PYTHONPATH`:

```bash
python -m doc_processing
```

This runs PDF conversion and enrichment only. It does not run the document indexing pipeline.

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

Indexing is a plain sequential loop: read resume state, read one target page,
extract target-page topics with previous/next-page continuity context, match
unresolved candidates backward through recent active topic batches, update or
append topics, save progress, then continue to the next page. It does not use
LangGraph.

By default indexing writes only product/resume artifacts. Add
`--write-diagnostics` to also write `revision_log.md`, `validation_report.json`,
and `backups/` for debugging.

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
|   |-- page_asset_registry.json
|   `-- stitched_raw_docling_markdown.md
|-- enriched_doc/
|   |-- pages_md/
|   |-- image_png_images/
|   |-- table_images/
|   |-- formula_images/
|   `-- readable_processed_doc.md
`-- indexing_output/
    |-- topic_index.json
    `-- processing_state.json
```

`page_asset_registry.json` records page-local figure, table, and formula assets
as each page is converted. Enrichment uses only the registry entry for the page
being processed; if a page-local asset cannot be placed exactly, it is preserved
in an `Unresolved Assets` section at the bottom of that same enriched page.

The readable markdown keeps old-style relative image links such as `![Table](table_images/table-1.png)` next to retrieval-friendly descriptions.

The topic index is a single continuous JSON list grouped only by topic. Page windows are internal to indexing and are not written into `topic_index.json`. Each topic entry contains `topic`, `pages`, a rich evidence-focused `description`, and `assets` for target-page figures, tables, and formulas. Legacy `keywords` entries can still be loaded, but new index writes use `assets` instead. Optional diagnostics are not product artifacts and are only written when requested.

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
|-- thought_analysis_bundle.json
|-- reports/executive_summary.md
|-- state/
|-- logs/
`-- artifact_cleanup.json
```

Reviewer downloads are exposed as CSV plus the Thought Analysis Bundle. The bundle
uses the canonical filename `thought_analysis_bundle.json` and contains observable
comparison artifacts only; it does not include hidden chain-of-thought.

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
