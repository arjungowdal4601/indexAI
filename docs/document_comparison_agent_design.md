# Document Comparison Agent Design

The document comparison layer is the product layer for SOP-vs-regulatory gap analysis.
It is separate from the retrieval demo and runs through the FastAPI backend or
the standalone `src/document_comparison` runner.

## Architecture

The comparison workflow is SOP-page anchored:

1. Read one SOP target page and the next SOP page as continuity context.
2. Plan structured SOP comparison items against the regulatory `topic_index.json`.
3. Read only the mapped regulatory page Markdown files.
4. Choose direct or compressed evidence mode per item.
5. Produce structured `GapFinding` records.
6. Aggregate item findings into page results and final reports.

The regulatory document is the required standard. The SOP document is the implemented/current procedure.
The output is page-wise, evidence-backed, conservative, and file-backed.

## Required Artifacts

The backend uses canonical role-specific document roots:

```text
storage/documents/regulatory/<regulatory_doc_id>/
storage/documents/sop/<sop_doc_id>/
```

Each root must contain `manifest.json`. The regulatory manifest must also point
to `indexing_output/topic_index.json`. The comparison package still accepts the
legacy `document_manifest.json` shape for manual/CLI compatibility.

## Outputs

Every run writes to:

```text
storage/comparisons/<comparison_id>/
```

Important outputs:

- `comparison_request.json`
- `plans/sop_page_XXXX_plan.json`
- `item_results/sop_page_XXXX_item_YYY.json`
- `page_reports/sop_page_XXXX.json`
- `final_report.json`
- `final_report.md`
- `final_report.csv`
- `reports/executive_summary.md`
- `traces/sop_page_XXXX_trace.json`

## Traceability

The reports expose observable planning, selected regulatory pages, memory mode,
evidence, reviewer-facing statuses, severities, and recommendations.
They do not expose hidden chain-of-thought.
