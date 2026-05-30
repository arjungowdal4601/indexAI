"""Sequential orchestration for document indexing."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import (
    DEFAULT_INCLUDE_NEXT_PAGE_CONTEXT,
    DEFAULT_TOPIC_MATCH_BATCH_SIZE,
)
from .llm import LangChainTopicIndexingClient, TopicIndexingClient
from .schemas import IndexingOutput, ProcessingState
from .steps import index_page
from .agent_guide import AGENT_MD_FILE, write_agent_memory_guide
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
        agent_md_path=output_folder / AGENT_MD_FILE,
    )


def _manifest_path_for_output(output_folder: Path) -> Path | None:
    manifest_path = output_folder.parent / "manifest.json"
    return manifest_path if manifest_path.exists() else None


def _write_agent_guide_if_index_exists(
    *,
    pages_folder_path: str | Path,
    output_folder: Path,
    document_id: str,
    original_filename: str | None,
) -> None:
    topic_index_path = output_folder / TOPIC_INDEX_FILE
    if not topic_index_path.exists():
        return
    manifest = read_page_manifest(pages_folder_path)
    write_agent_memory_guide(
        output_dir=output_folder,
        document_id=document_id,
        original_filename=original_filename,
        total_pages=manifest.total_pages,
        topic_index_path=topic_index_path,
        manifest_path=_manifest_path_for_output(output_folder),
    )


def run_document_indexing(
    pages_folder_path: str | Path,
    output_folder_path: str | Path,
    document_id: str,
    original_filename: str | None = None,
    include_next_page_context: bool = DEFAULT_INCLUDE_NEXT_PAGE_CONTEXT,
    client: TopicIndexingClient | None = None,
    topic_match_batch_size: int = DEFAULT_TOPIC_MATCH_BATCH_SIZE,
    write_diagnostics: bool = False,
    event_callback: Callable[[str, str, str, int | None, int | None], None] | None = None,
) -> IndexingOutput:
    output_folder = Path(output_folder_path)
    output_folder.mkdir(parents=True, exist_ok=True)

    processing_state = load_processing_state(
        output_dir=output_folder,
        document_id=document_id,
    )
    if processing_state.status == "completed":
        _write_agent_guide_if_index_exists(
            pages_folder_path=pages_folder_path,
            output_folder=output_folder,
            document_id=document_id,
            original_filename=original_filename,
        )
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
            topic_match_batch_size=topic_match_batch_size,
            write_diagnostics=write_diagnostics,
            step_number=step_number,
            event_callback=event_callback,
        )

    _write_agent_guide_if_index_exists(
        pages_folder_path=pages_folder_path,
        output_folder=output_folder,
        document_id=document_id,
        original_filename=original_filename,
    )
    return _indexing_output(output_folder)
