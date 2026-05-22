"""Legacy standalone retrieval demo. The active UI is frontend/streamlit_app.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from document_retrieval.config import (  # noqa: E402
    DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    DEFAULT_MAX_DIRECT_PAGES,
    DEFAULT_PAGES_FOLDER,
    DEFAULT_TOPIC_INDEX_PATH,
)
from document_retrieval.llm import LangChainRetrievalClient  # noqa: E402
from document_retrieval.nodes import (  # noqa: E402
    answer_from_compressed_evidence_node,
    answer_from_pages_node,
    build_retrieval_trace_node,
    check_page_files_exist_node,
    compress_page_evidence_node,
    estimate_context_size_node,
    load_topic_index_node,
    read_selected_pages_node,
    route_query_to_topics_node,
)


DEFAULT_QUERY = (
    "Explain how scaled dot-product attention and multi-head attention are "
    "computed in the paper. Include both formulas, why the dot products are "
    "scaled by 1/sqrt(d_k), and how multi-head attention is used in "
    "encoder-decoder attention, encoder self-attention, and masked decoder "
    "self-attention."
)

DEMO_MODEL_OVERRIDE = None
DEMO_MARKDOWN_PREVIEW_CHARS = 3000


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def compact_json(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, indent=2)


def infer_asset_root(pages_folder_path: Path) -> Path:
    if pages_folder_path.name == "pages_md" and pages_folder_path.parent.name == "enriched_doc":
        return pages_folder_path.parent.parent
    return pages_folder_path.parent


def default_page_images_folder(pages_folder_path: Path) -> Path:
    return infer_asset_root(pages_folder_path) / "docling_assets" / "page_images"


def page_image_path(page_images_folder: Path, page_number: int) -> Path:
    return page_images_folder / f"page-{page_number}.png"


def summarize_step(name: str, state: dict[str, Any], update: dict[str, Any]) -> str:
    if name == "load_topic_index":
        return f"Loaded {len(state.get('topic_index', []))} topics."
    if name == "route_query_to_topics":
        pages = state.get("selected_pages", [])
        route_count = len(getattr(state.get("routing_decision"), "routes", []))
        return f"Selected {len(pages)} pages from {route_count} matched topic routes."
    if name == "check_page_files_exist":
        return "All selected page Markdown files exist."
    if name == "read_selected_pages":
        return f"Read {len(state.get('page_contexts', []))} selected page Markdown files."
    if name == "estimate_context_size":
        return (
            f"Estimated {state.get('estimated_context_tokens', 0)} tokens; "
            f"memory mode is {state.get('memory_mode')}."
        )
    if name == "compress_page_evidence":
        return f"Compressed evidence from {len(state.get('compressed_evidence', []))} pages."
    if name in {"answer_from_pages", "answer_from_compressed_evidence"}:
        answer = state.get("final_answer")
        pages_used = getattr(answer, "pages_used", [])
        return f"Generated answer citing {len(pages_used)} pages."
    if name == "build_retrieval_trace":
        trace = state.get("retrieval_trace", {})
        pages_read = trace.get("pages_read", []) if isinstance(trace, dict) else []
        return f"Built retrieval trace for {len(pages_read)} pages read."
    return f"Updated keys: {', '.join(update.keys()) or 'none'}."


def run_node_step(
    steps: list[dict[str, Any]],
    state: dict[str, Any],
    name: str,
    node,
) -> bool:
    try:
        update = node(state)
        state.update(update)
        steps.append(
            {
                "step": name,
                "status": "completed",
                "summary": summarize_step(name, state, update),
                "output": to_jsonable(update),
            }
        )
        return True
    except Exception as exc:
        steps.append(
            {
                "step": name,
                "status": "failed",
                "summary": f"{type(exc).__name__}: {exc}",
            }
        )
        return False


def run_debug_retrieval(
    user_query: str,
    topic_index_path: Path,
    pages_folder_path: Path,
    model: str | None,
    max_direct_pages: int,
    max_direct_estimated_tokens: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state: dict[str, Any] = {
        "user_query": user_query,
        "topic_index_path": topic_index_path,
        "pages_folder_path": pages_folder_path,
        "max_direct_pages": int(max_direct_pages),
        "max_direct_estimated_tokens": int(max_direct_estimated_tokens),
    }
    steps: list[dict[str, Any]] = []

    try:
        state["client"] = LangChainRetrievalClient(model=model)
        steps.append(
            {
                "step": "initialize_client",
                "status": "completed",
                "summary": "Initialized LangChain retrieval client.",
                "output": {"model_override": model or ""},
            }
        )
    except Exception as exc:
        steps.append(
            {
                "step": "initialize_client",
                "status": "failed",
                "summary": f"{type(exc).__name__}: {exc}",
            }
        )
        return state, steps

    for name, node in [
        ("load_topic_index", load_topic_index_node),
        ("route_query_to_topics", route_query_to_topics_node),
        ("check_page_files_exist", check_page_files_exist_node),
        ("read_selected_pages", read_selected_pages_node),
        ("estimate_context_size", estimate_context_size_node),
    ]:
        if not run_node_step(steps, state, name, node):
            return state, steps

    if state.get("memory_mode") == "compressed":
        if not run_node_step(steps, state, "compress_page_evidence", compress_page_evidence_node):
            return state, steps
        if not run_node_step(
            steps,
            state,
            "answer_from_compressed_evidence",
            answer_from_compressed_evidence_node,
        ):
            return state, steps
    else:
        if not run_node_step(steps, state, "answer_from_pages", answer_from_pages_node):
            return state, steps

    run_node_step(steps, state, "build_retrieval_trace", build_retrieval_trace_node)
    return state, steps


def build_thought_analysis_bundle(
    user_query: str,
    state: dict[str, Any],
    steps: list[dict[str, Any]],
    page_images_folder: Path,
) -> str:
    page_contexts = state.get("page_contexts", [])
    page_sources = []
    for context in page_contexts:
        image_path = page_image_path(page_images_folder, context.page)
        page_sources.append(
            {
                "page": context.page,
                "markdown_file": str(context.path),
                "page_image": str(image_path),
                "markdown_excerpt": context.markdown[:3000],
            }
        )

    bundle = {
        "user_query": user_query,
        "answer": to_jsonable(state.get("final_answer")),
        "retrieval_trace": to_jsonable(state.get("retrieval_trace")),
        "routing_decision": to_jsonable(state.get("routing_decision")),
        "selected_pages": to_jsonable(state.get("selected_pages", [])),
        "estimated_context_tokens": state.get("estimated_context_tokens"),
        "memory_mode": state.get("memory_mode"),
        "compressed_evidence": to_jsonable(state.get("compressed_evidence", [])),
        "page_sources": page_sources,
        "debug_steps": steps,
    }
    return compact_json(bundle)


def render_debug_steps(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        status = step["status"]
        label = "[OK]" if status == "completed" else "[FAILED]"
        with st.expander(f"{label} {step['step']}", expanded=status != "completed"):
            st.write(step["summary"])
            if "output" in step:
                st.json(step["output"])


def render_route_tab(state: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    render_debug_steps(steps)
    decision = state.get("routing_decision")
    if not decision:
        st.info("Run retrieval to see topic routing.")
        return

    st.subheader("Routing Decision")
    st.json(to_jsonable(decision))
    st.subheader("Selected Pages")
    st.write(state.get("selected_pages", []))


def render_pages_tab(state: dict[str, Any], page_images_folder: Path, preview_chars: int) -> None:
    page_contexts = state.get("page_contexts", [])
    if not page_contexts:
        st.info("Run retrieval to see selected pages and page images.")
        return

    for context in page_contexts:
        st.subheader(f"Page {context.page}")
        image_path = page_image_path(page_images_folder, context.page)
        left, right = st.columns([1, 1])
        with left:
            if image_path.exists():
                st.image(str(image_path), caption=str(image_path), width="stretch")
            else:
                st.warning(f"Page image not found: {image_path}")
        with right:
            st.caption(str(context.path))
            st.text_area(
                f"Markdown preview for page {context.page}",
                context.markdown[:preview_chars],
                height=420,
                key=f"page-markdown-{context.page}",
            )


def render_memory_tab(state: dict[str, Any]) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Estimated tokens", state.get("estimated_context_tokens", 0))
    col2.metric("Memory mode", state.get("memory_mode", "not run"))
    col3.metric("Pages read", len(state.get("page_contexts", [])))

    compressed = state.get("compressed_evidence")
    if compressed:
        st.subheader("Compressed Evidence")
        st.json(to_jsonable(compressed))
    else:
        st.info("Compressed evidence appears only when the selected context exceeds the direct budget.")


def render_answer_tab(state: dict[str, Any]) -> None:
    answer = state.get("final_answer")
    trace = state.get("retrieval_trace")
    if not answer:
        st.info("Run retrieval to see the answer.")
        return

    st.subheader("Answer")
    st.write(answer.answer)
    st.subheader("Pages Used")
    st.write(answer.pages_used)
    st.subheader("Missing Information")
    if answer.missing_information:
        for item in answer.missing_information:
            st.write(f"- {item}")
    else:
        st.write("None reported.")

    st.subheader("Retrieval Trace")
    st.json(to_jsonable(trace))


def render_thought_analysis_bundle_tab(
    user_query: str,
    state: dict[str, Any],
    steps: list[dict[str, Any]],
    page_images_folder: Path,
) -> None:
    st.caption("Copy this bundle for retrieval thought analysis and answer review.")
    st.text_area(
        "Thought analysis bundle",
        build_thought_analysis_bundle(user_query, state, steps, page_images_folder),
        height=620,
    )


def main() -> None:
    load_dotenv_if_available()
    st.set_page_config(
        page_title="Vectorless RAG Retrieval Demo",
        page_icon="",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            display: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Vectorless RAG Retrieval Demo")
    st.caption("Topic-index navigation with page-level evidence and traceable retrieval steps.")

    topic_index_path = DEFAULT_TOPIC_INDEX_PATH
    pages_folder_path = DEFAULT_PAGES_FOLDER
    page_images_folder = default_page_images_folder(pages_folder_path)
    model_override = DEMO_MODEL_OVERRIDE
    max_direct_pages = DEFAULT_MAX_DIRECT_PAGES
    max_direct_estimated_tokens = DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS
    preview_chars = DEMO_MARKDOWN_PREVIEW_CHARS

    user_query = st.text_area("Question", value=DEFAULT_QUERY, height=100)
    run_clicked = st.button("Run retrieval", type="primary")

    if "debug_state" not in st.session_state:
        st.session_state.debug_state = {}
    if "debug_steps" not in st.session_state:
        st.session_state.debug_steps = []

    if run_clicked:
        with st.spinner("Running vectorless retrieval..."):
            state, steps = run_debug_retrieval(
                user_query=user_query,
                topic_index_path=topic_index_path,
                pages_folder_path=pages_folder_path,
                model=model_override,
                max_direct_pages=int(max_direct_pages),
                max_direct_estimated_tokens=int(max_direct_estimated_tokens),
            )
        st.session_state.debug_state = state
        st.session_state.debug_steps = steps

    state = st.session_state.debug_state
    steps = st.session_state.debug_steps

    if steps and steps[-1]["status"] == "failed":
        st.error(steps[-1]["summary"])

    route_tab, pages_tab, memory_tab, answer_tab, bundle_tab = st.tabs(
        ["Route", "Pages", "Memory", "Answer", "Thought Analysis Bundle"]
    )
    with route_tab:
        render_route_tab(state, steps)
    with pages_tab:
        render_pages_tab(state, page_images_folder, preview_chars)
    with memory_tab:
        render_memory_tab(state)
    with answer_tab:
        render_answer_tab(state)
    with bundle_tab:
        render_thought_analysis_bundle_tab(user_query, state, steps, page_images_folder)


if __name__ == "__main__":
    main()
