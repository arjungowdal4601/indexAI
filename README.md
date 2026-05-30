# IndexAI

IndexAI turns one uploaded PDF into vectorless document memory.

It is not a vector database project. It does not use embeddings, Chroma, or a semantic chunk store. Retrieval is grounded in two artifacts produced from the PDF:

- `topic_index.json`: the memory map from topics to exact page numbers.
- `agent.md`: the operating guide that tells an agent how to use the memory map.

## Vectorless Memory Flow

```text
upload PDF
  -> process pages with Docling
  -> enrich page Markdown
  -> build topic_index.json
  -> write agent.md
  -> ask questions in Document Co-pilot
```

The co-pilot reads `topic_index.json` first, routes the user question to candidate topics and pages, reads only the selected files from `enriched_doc/pages_md`, then answers from that grounded evidence. If the selected pages are too large for the direct context budget, it compresses page evidence first and answers from the compressed evidence.

## Artifacts

Each uploaded document gets its own folder under the storage root:

```text
storage/documents/<document_id>/
|-- original/source.pdf
|-- manifest.json
|-- docling_assets/
|   `-- page_images/
|-- enriched_doc/
|   `-- pages_md/
|       |-- page_0001.md
|       `-- page_0002.md
`-- indexing_output/
    |-- topic_index.json
    |-- processing_state.json
    |-- revision_log.md
    `-- agent.md
```

`topic_index.json` is the page-level memory map. It stores topic names, page lists, descriptions, and asset summaries.

`agent.md` is the agent operating guide. It tells downstream agents to read the topic index first, select the smallest useful page set, then read only the matching enriched Markdown pages.

## Run Locally

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Start the FastAPI backend:

```powershell
$env:PYTHONPATH = ".\src"
uvicorn backend.app:app --reload
```

Start Streamlit in a second terminal:

```powershell
$env:PYTHONPATH = ".\src"
$env:INDEXAI_API_BASE_URL = "http://127.0.0.1:8000"
streamlit run frontend/streamlit_app.py
```

Or run both services together from the `compute` Conda environment:

```powershell
.\run_indexai_app.ps1
```

The app opens at `http://127.0.0.1:8501` and talks to the backend at `http://127.0.0.1:8000`.

## App Workflow

1. Open **Upload and Index**.
2. Upload one PDF.
3. Click **Index** to process pages and build document memory.
4. Wait until the document shows **Indexed**.
5. Open **Document Co-pilot** and ask questions against any indexed document.

The home page shows three product metrics:

- Documents
- Processed
- Indexed

## API

Primary endpoints:

```text
GET /health
POST /documents/upload
GET /documents
POST /documents/{document_id}/prepare
POST /documents/{document_id}/process
POST /documents/{document_id}/index
GET /jobs/{job_id}
GET /jobs/{job_id}/events
POST /documents/{document_id}/copilot/query
GET /assets/documents/{document_id}/page-image/{page_number}
```

Set a custom storage root with:

```powershell
$env:INDEXAI_STORAGE_ROOT = "C:\path\to\storage"
```

Set a custom frontend backend URL with:

```powershell
$env:INDEXAI_API_BASE_URL = "http://127.0.0.1:8000"
```

## CLI Entrypoints

Run document processing only:

```powershell
$env:PYTHONPATH = ".\src"
python main.py
```

Run topic indexing after enriched page Markdown exists:

```powershell
$env:PYTHONPATH = ".\src"
python src/document_indexing/main.py --pages-folder storage/documents/doc_000001/enriched_doc/pages_md
```

Run retrieval after `topic_index.json` exists:

```powershell
$env:PYTHONPATH = ".\src"
python src/document_retrieval/main.py --topic-index storage/documents/doc_000001/indexing_output/topic_index.json --pages-folder storage/documents/doc_000001/enriched_doc/pages_md "What does this document say?"
```

## Tests

Run the full suite:

```powershell
python -m pytest -q
```
