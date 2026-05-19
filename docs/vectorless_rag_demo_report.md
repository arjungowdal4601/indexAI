# Vectorless RAG Retrieval System Demo Report

## Executive Summary

This repository implements a three-stage document question-answering system:

1. **Document processing** converts a PDF into page-level Markdown, page images, and enriched visual descriptions.
2. **Document indexing** builds a human-readable `topic_index.json` with topic names, page references, rich descriptions, and figure/table/formula assets.
3. **Document retrieval** answers a user query by navigating the topic index, reading only selected page Markdown files, and returning a cited answer with a deterministic retrieval trace.

The system is "vectorless" because it does not embed chunks into a vector database for query-time retrieval. Instead, it uses a structured topic map plus controlled LangGraph workflows. This makes the retrieval route easier to inspect, debug, and tune for high-trust document QA.

## 1. System Architecture

The project keeps the three stages separate instead of creating one monolithic pipeline.

```text
PDF
  -> document processing
  -> enriched page Markdown + page images + visual assets
  -> document indexing agent
  -> topic_index.json
  -> document retrieval agent
  -> cited answer + retrieval trace
  -> Streamlit demo UI
```

The main architectural rule is simple:

- Use **document processing** to make the PDF readable.
- Use **document indexing** to make the document navigable.
- Use **document retrieval** to read only the evidence needed for one question.

The root `python main.py` entrypoint runs document processing only. Indexing and retrieval are separate runnable packages so they can be debugged, regenerated, and demonstrated independently.

## 2. Document Processing Stage

Document processing is a pipeline, not the retrieval agent. Its job is to turn a PDF into clean artifacts that later stages can trust.

Code location:

- `src/doc_processing/pipeline.py`
- `src/doc_processing/docling_converter.py`
- `src/doc_processing/table_detection.py`
- `src/doc_processing/enrichment.py`
- `src/doc_processing/prompts.py`

Processing steps:

1. **Docling conversion**
   - Reads the source PDF.
   - Produces page-wise raw Markdown.
   - Extracts page images, figure images, table images, and formula images.
   - Writes assets under `sample_doc_assets/docling_assets/`.

2. **Table continuity detection**
   - Detects table fragments that may continue across pages.
   - Writes `table_continuity_map.json`.
   - This is deterministic and does not use an LLM.

3. **Enrichment**
   - Adds retrieval-friendly descriptions for figures, tables, and formulas.
   - Produces readable page Markdown under `sample_doc_assets/enriched_doc/pages_md/`.
   - Copies visual asset folders so enriched Markdown can still point to local asset paths.

Important output shape:

```text
sample_doc_assets/
|-- docling_assets/
|   |-- pages_md/
|   |-- page_images/
|   |-- image_png_images/
|   |-- table_images/
|   |-- formula_images/
|   `-- table_continuity_map.json
`-- enriched_doc/
    |-- pages_md/
    |-- image_png_images/
    |-- table_images/
    |-- formula_images/
    `-- readable_processed_doc.md
```

Why this matters:

- Retrieval should not depend on unreadable PDF layout.
- Images, tables, and formulas need text descriptions because later agents make text-based decisions.
- Page-level files preserve source traceability.

## 3. Document Indexing Agent

Document indexing is an agentic LangGraph workflow. It reads enriched page Markdown and writes the navigation layer: `topic_index.json`.

Code location:

- `src/document_indexing/graph.py`
- `src/document_indexing/nodes.py`
- `src/document_indexing/prompts.py`
- `src/document_indexing/schemas.py`
- `src/document_indexing/storage.py`
- `src/document_indexing/validator.py`

The graph uses explicit nodes:

```text
load_state
  -> read_manifest
  -> read_index
  -> read_window
  -> extract_candidates
  -> match_candidates
  -> update_index
  -> write_outputs
  -> read_index or END
```

The indexing method is target-page based:

- Send **previous page indexed topics** as continuity hints.
- Send the **full target page Markdown** as the only indexable evidence.
- Send the **full next page Markdown** only to detect continuation boundaries.
- Extract assets only from the target page.
- Merge candidates into existing topics only when they are true continuations or semantic matches.

Current public topic index contract:

```json
{
  "topic": "Attention and scaled dot-product attention setup",
  "pages": [2, 3, 4],
  "description": "Rich evidence-focused description with exact terms and formulas.",
  "assets": [
    {
      "page": 4,
      "type": "formula",
      "path": "formula_images/formula-1.png",
      "description": "LaTeX: Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V"
    }
  ]
}
```

Why indexing is needed:

- The retrieval agent should not scan every page for every question.
- The topic index is a compact navigation map.
- Rich descriptions replace noisy keyword lists.
- Assets make formula/table/figure questions easier to route.

## 4. Document Retrieval Agent

Document retrieval is also an agentic LangGraph workflow. It receives one full user query and maps it directly to relevant topics and pages.

Code location:

- `src/document_retrieval/graph.py`
- `src/document_retrieval/nodes.py`
- `src/document_retrieval/prompts.py`
- `src/document_retrieval/schemas.py`
- `src/document_retrieval/storage.py`

The graph uses explicit nodes:

```text
START
  -> load_topic_index
  -> route_query_to_topics
  -> check_page_files_exist
  -> read_selected_pages
  -> estimate_context_size
  -> direct: answer_from_pages
  -> compressed: compress_page_evidence -> answer_from_compressed_evidence
  -> build_retrieval_trace
  -> END
```

Retrieval behavior:

- The full user query is routed against the topic index.
- The router selects the minimum sufficient topics and pages.
- Only selected `page_XXXX.md` files are read.
- The system estimates context size.
- If selected context fits the memory budget, it answers directly from pages.
- If selected context is too large, it compresses page evidence first.
- The final answer includes page citations and missing information if evidence is insufficient.

The trace is deterministic:

```json
{
  "matched_topics": ["Attention and scaled dot-product attention setup"],
  "pages_read": [4, 5],
  "files_read": ["page_0004.md", "page_0005.md"],
  "memory_mode": "direct",
  "selection_reason": "Why these pages were chosen."
}
```

This is the main trust advantage of the system: we can inspect the retrieval path, not just the answer.

## 5. Streamlit Demo UI

The Streamlit app is a temporary demo surface for showing the retrieval process.

Code location:

- `app.py`

The UI shows:

- Query input.
- Route tab: routing decision, matched topics, selected pages, debug steps.
- Pages tab: selected page images and Markdown previews.
- Memory tab: estimated tokens, memory mode, pages read, compressed evidence when used.
- Answer tab: final answer, pages used, missing information, retrieval trace.
- Thought Analysis Bundle: copyable JSON for reviewing the retrieval route and answer quality.

The UI does not expose hidden chain-of-thought. It exposes the observable evidence path:

- what route was chosen,
- which page files were read,
- what memory mode was used,
- what answer was produced,
- what source page images and Markdown excerpts support it.

## 6. Why This Is Vectorless RAG

Traditional vector RAG usually follows this shape:

```text
documents -> chunks -> embeddings -> vector database
query -> query embedding -> nearest-neighbor search -> top-k chunks -> answer
```

This project follows a different shape:

```text
documents -> enriched pages -> topic index
query -> topic/page routing -> selected page Markdown -> answer
```

The system still does retrieval-augmented generation because the model answers from external document evidence at query time. It is vectorless because the retrieval layer is a topic/page routing workflow instead of an embedding similarity search.

## 7. Vector RAG vs Vectorless RAG

| Dimension | Vector RAG | Vectorless RAG in this repo |
| --- | --- | --- |
| Retrieval mechanism | Embedding similarity search over chunks | LLM routes query through `topic_index.json` |
| Data layer | Vector database or vector index | JSON topic index plus page Markdown files |
| Strength | Fast, scalable semantic search over large corpora | Controllable, inspectable page-level retrieval |
| Debuggability | Harder to see why a chunk ranked high beyond similarity score | Trace shows matched topics, pages, files, memory mode |
| Tuning lever | Chunking, embedding model, metadata filters, reranking | Prompt rules, topic descriptions, assets, page-selection guardrails |
| Failure diagnosis | Retrieval miss may be due to chunking, embedding drift, ranking, or metadata | Easier to isolate indexing issue vs routing issue vs page evidence issue |
| Cost/latency | Usually faster at query time after indexing | Can be slower and more costly because LLM decisions are used |
| Best fit | Broad semantic search, large-scale corpora, fuzzy matching | High-trust document QA, structured PDFs, audit/debug demos |

The practical argument is not "vectorless RAG is always better." The argument is:

- If scale and latency dominate, vector RAG is usually the stronger baseline.
- If traceability, controllability, and debugging dominate, vectorless RAG is worth considering.
- For a demo or regulated-document workflow, showing the exact route and page evidence can be more valuable than retrieving opaque top-k chunks.

## 8. Web-Backed Context

IBM describes RAG as connecting an LLM to external knowledge at query time and notes that vector databases store and retrieve numerical embeddings for semantic similarity. IBM also notes that RAG can use keyword search, structured queries, or hybrid approaches depending on the use case, so vector search is not strictly required.

Pinecone's semantic search documentation describes vector search as finding semantically similar records using dense vectors, where a query text can be converted into a dense vector and searched with `top_k` results.

DigitalOcean's overview of RAG without embeddings describes traditional RAG as chunking documents, embedding them, storing them in a vector database, and using nearest-neighbor search. It also highlights limitations such as semantic gaps, infrastructure overhead, and lower interpretability, while describing embedding-free alternatives such as keyword search, GraphRAG-style structure, and prompt-based retrieval.

LangGraph's Graph API documentation supports this repo's explicit graph structure: graph workflows are composed from state, nodes, and edges, where nodes do work and edges decide what runs next.

LangChain's structured output documentation supports the repo's Pydantic model contract: structured output returns predictable data instead of free-form natural language.

References:

- IBM, "What are RAG vector databases?" https://www.ibm.com/think/topics/rag-vector-database
- Pinecone, "Semantic search." https://docs.pinecone.io/guides/search/semantic-search
- DigitalOcean, "Beyond Vector Databases: RAG Architectures Without Embeddings." https://www.digitalocean.com/community/tutorials/beyond-vector-databases-rag-without-embeddings
- LangGraph, "Graph API overview." https://docs.langchain.com/oss/python/langgraph/graph-api
- LangChain, "Structured output." https://docs.langchain.com/oss/python/langchain/structured-output

## 9. Demo Talking Track

Use this sequence for the live demo:

1. Start with the PDF problem: pages contain text, formulas, tables, and figures, and raw PDF extraction is not enough.
2. Show document processing artifacts: page images, enriched Markdown, figure/table/formula descriptions.
3. Show `topic_index.json`: topic names, pages, descriptions, and assets.
4. Ask the Streamlit question about scaled dot-product attention and multi-head attention.
5. Open Route: show the matched topics and selected pages.
6. Open Pages: show page images and Markdown evidence.
7. Open Memory: show direct mode vs compressed mode.
8. Open Answer: show citations and missing-information behavior.
9. Open Thought Analysis Bundle: explain that this is the evidence trail used for review.
10. Finish with vector RAG vs vectorless RAG: vector RAG is fast and scalable; vectorless RAG is controllable, debuggable, and trust-oriented.

## 10. Summary

This system is built for transparent document QA. The document processing stage creates clean evidence. The indexing agent creates a navigable topic map. The retrieval agent reads only selected pages and produces an answer with citations and a retrieval trace. Compared with vector RAG, it trades some latency and cost for route control, page-level proof, and easier debugging.
