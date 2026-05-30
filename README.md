# IndexAI

IndexAI turns one uploaded PDF into vectorless document memory.

The app flow is:

1. Upload one PDF.
2. Process it into page text, page images, and enriched Markdown.
3. Index the enriched pages into `topic_index.json`.
4. Ask questions against that indexed document with Document Co-pilot.

## Structure

```text
indexAI/
|-- backend/
|   |-- app.py
|   |-- api/
|   `-- services/
|-- frontend/
|   |-- streamlit_app.py
|   `-- pages/
|-- src/
|   |-- doc_processing/
|   |-- document_indexing/
|   `-- document_retrieval/
|-- tests/
|-- requirements.txt
`-- run_indexai_app.ps1
```

## Run The App

Install dependencies:

```bash
pip install -r requirements.txt
```

Start FastAPI from the project root:

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

The script starts FastAPI on `http://127.0.0.1:8000` and Streamlit on
`http://127.0.0.1:8501`, then stops both services when you press `Ctrl+C`.

## Document Workflow

The Streamlit app has two main pages:

- **Upload and Prepare**: upload a PDF, process it, and build the topic index.
- **Document Co-pilot**: ask questions against any processed and indexed document.

Prepared documents follow this lifecycle:

```text
upload -> processing -> indexing -> memory ready
```

`topic_index.json` is written under each document's `indexing_output/` folder.
Document Co-pilot reads that index and the enriched page Markdown files at query time.

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

The backend uses `storage/` by default. Override it with:

```powershell
$env:INDEXAI_STORAGE_ROOT = "C:\path\to\storage"
```

## Pipeline Entrypoints

Run document processing only:

```bash
python main.py
```

Run topic indexing directly after enriched page Markdown exists:

```bash
python src/document_indexing/main.py
```

Run document retrieval directly after `topic_index.json` exists:

```bash
python src/document_retrieval/main.py "What does this document say?"
```
