"""Sequential orchestration for document indexing."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import (
    DEFAULT_INCLUDE_NEXT_PAGE_CONTEXT,
    DEFAULT_TOPIC_INDEX_TOKEN_LIMIT,
)
from .llm import LangChainTopicIndexingClient, TopicIndexingClient
from .schemas import IndexingOutput, ProcessingState
from .steps import index_page
from .storage import (
    PROCESSING_STATE_FILE,
    REVISION_LOG_FILE,
    TOPIC_INDEX_FILE,
    VALIDATION_REPORT_FILE,
    load_processing_state,
    load_topic_index,
    read_page_manifest,
    read_page_window,
    write_processing_state,
)


def _indexing_output(output_folder: Path) -> IndexingOutput:
    return IndexingOutput(
        topic_index_path=output_folder / TOPIC_INDEX_FILE,
        processing_state_path=output_folder / PROCESSING_STATE_FILE,
        revision_log_path=output_folder / REVISION_LOG_FILE,
        validation_report_path=output_folder / VALIDATION_REPORT_FILE,
    )


def run_document_indexing(
    pages_folder_path: str | Path,
    output_folder_path: str | Path,
    document_id: str,
    include_next_page_context: bool = DEFAULT_INCLUDE_NEXT_PAGE_CONTEXT,
    client: TopicIndexingClient | None = None,
    token_limit: int = DEFAULT_TOPIC_INDEX_TOKEN_LIMIT,
    event_callback: Callable[[str, str, str, int | None, int | None], None] | None = None,
) -> IndexingOutput:
    output_folder = Path(output_folder_path)
    output_folder.mkdir(parents=True, exist_ok=True)

    processing_state = load_processing_state(
        output_dir=output_folder,
        document_id=document_id,
    )
    if processing_state.status == "completed":
        return _indexing_output(output_folder)

    manifest = read_page_manifest(pages_folder_path)
    if manifest.missing_pages:
        raise FileNotFoundError(f"Missing page markdown files: {manifest.missing_pages}")

    indexing_client = client or LangChainTopicIndexingClient()
    step_number = 0
    while processing_state.status != "completed":
        if processing_state.next_start_page > manifest.total_pages:
            processing_state = ProcessingState(
                document_id=document_id,
                last_completed_page=processing_state.last_completed_page,
                next_start_page=processing_state.next_start_page,
                status="completed",
            )
            write_processing_state(output_folder, processing_state)
            break

        current_topic_index = load_topic_index(output_folder / TOPIC_INDEX_FILE)
        window = read_page_window(
            manifest=manifest,
            target_page=processing_state.next_start_page,
            current_topic_index=current_topic_index,
            include_next_page=include_next_page_context,
        )
        processing_state, step_number = index_page(
            output_dir=output_folder,
            document_id=document_id,
            processing_state=processing_state,
            manifest=manifest,
            window=window,
            current_topic_index=current_topic_index,
            client=indexing_client,
            token_limit=int(token_limit),
            step_number=step_number,
            event_callback=event_callback,
        )

    return _indexing_output(output_folder)
