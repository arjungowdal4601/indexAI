"""Thin HTTP client for the FastAPI backend."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
API_BASE_URL_ENV = "DOC_COMPARING_API_BASE_URL"
DEFAULT_TIMEOUT_SECONDS = 30


class ApiError(RuntimeError):
    """Raised when the backend returns an error or cannot be reached."""


def get_api_base_url(base_url: str | None = None) -> str:
    return (base_url or os.getenv(API_BASE_URL_ENV) or DEFAULT_API_BASE_URL).rstrip("/")


def absolute_url(path_or_url: str, base_url: str | None = None) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    return f"{get_api_base_url(base_url)}{path_or_url}"


def page_image_path(document_id: str, page_number: int) -> str:
    return f"/assets/documents/{document_id}/page-image/{int(page_number)}"


def _decode_response(response) -> dict[str, Any]:
    body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    base_url: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = f"{get_api_base_url(base_url)}{path}"
    if query:
        query_string = urlencode({key: value for key, value in query.items() if value is not None})
        if query_string:
            url = f"{url}?{query_string}"
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return _decode_response(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"Backend returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ApiError(f"Could not reach backend at {url}: {exc.reason}") from exc


def _request_bytes(
    method: str,
    path: str,
    base_url: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    accept: str = "*/*",
) -> bytes:
    url = f"{get_api_base_url(base_url)}{path}"
    request = Request(url, headers={"Accept": accept}, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"Backend returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ApiError(f"Could not reach backend at {url}: {exc.reason}") from exc


def health(base_url: str | None = None) -> dict[str, Any]:
    return _request_json("GET", "/health", base_url=base_url)


def list_documents(document_type: str | None = None, base_url: str | None = None) -> dict[str, Any]:
    return _request_json(
        "GET",
        "/documents",
        query={"document_type": document_type},
        base_url=base_url,
    )


def start_processing(document_id: str, base_url: str | None = None) -> dict[str, Any]:
    return _request_json("POST", f"/documents/{document_id}/process", base_url=base_url)


def start_prepare(
    document_id: str,
    base_url: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"/documents/{document_id}/prepare",
        base_url=base_url,
        timeout=timeout,
    )


def start_indexing(document_id: str, base_url: str | None = None) -> dict[str, Any]:
    return _request_json("POST", f"/documents/{document_id}/index", base_url=base_url)


def get_job(job_id: str, base_url: str | None = None) -> dict[str, Any]:
    return _request_json("GET", f"/jobs/{job_id}", base_url=base_url)


def get_job_events(job_id: str, base_url: str | None = None) -> dict[str, Any]:
    return _request_json("GET", f"/jobs/{job_id}/events", base_url=base_url)


def create_comparison(
    regulatory_document_id: str,
    sop_document_id: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        "/comparisons",
        payload={
            "regulatory_document_id": regulatory_document_id,
            "sop_document_id": sop_document_id,
        },
        base_url=base_url,
    )


def list_comparisons(base_url: str | None = None) -> dict[str, Any]:
    return _request_json("GET", "/comparisons", base_url=base_url)


def get_comparison(comparison_id: str, base_url: str | None = None) -> dict[str, Any]:
    return _request_json("GET", f"/comparisons/{comparison_id}", base_url=base_url)


def get_active_comparison_for_pair(
    regulatory_document_id: str,
    sop_document_id: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    return _request_json(
        "GET",
        "/comparisons/by-pair/active",
        query={
            "regulatory_document_id": regulatory_document_id,
            "sop_document_id": sop_document_id,
        },
        base_url=base_url,
    )


def get_comparison_progress(comparison_id: str, base_url: str | None = None) -> dict[str, Any]:
    return _request_json("GET", f"/comparisons/{comparison_id}/progress", base_url=base_url)


def get_comparison_report(comparison_id: str, base_url: str | None = None) -> dict[str, Any]:
    return _request_json("GET", f"/comparisons/{comparison_id}/report", base_url=base_url)


def download_comparison_csv(comparison_id: str, base_url: str | None = None) -> bytes:
    return _request_bytes(
        "GET",
        f"/comparisons/{comparison_id}/downloads/csv",
        base_url=base_url,
        accept="text/csv",
    )


def download_thought_analysis_bundle(
    comparison_id: str,
    base_url: str | None = None,
) -> bytes:
    return _request_bytes(
        "GET",
        f"/comparisons/{comparison_id}/downloads/thought-analysis-bundle",
        base_url=base_url,
        accept="application/json",
    )


def get_page_report(
    comparison_id: str,
    sop_page_number: int,
    base_url: str | None = None,
) -> dict[str, Any]:
    return _request_json(
        "GET",
        f"/comparisons/{comparison_id}/pages/{int(sop_page_number)}",
        base_url=base_url,
    )


def copilot_query(
    document_id: str,
    query: str,
    base_url: str | None = None,
    max_direct_pages: int = 10,
    max_direct_estimated_tokens: int = 70000,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"/documents/{document_id}/copilot/query",
        payload={
            "query": query,
            "max_direct_pages": max_direct_pages,
            "max_direct_estimated_tokens": max_direct_estimated_tokens,
        },
        base_url=base_url,
        timeout=120,
    )


def upload_document(
    document_type: str,
    filename: str,
    content: bytes,
    base_url: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    boundary = f"----doc-comparing-{uuid.uuid4().hex}"
    body_parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="document_type"\r\n\r\n'
        f"{document_type}\r\n",
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n",
    ]
    body = "".join(body_parts).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    request = Request(
        f"{get_api_base_url(base_url)}/documents/upload",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return _decode_response(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"Backend returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ApiError(f"Could not reach backend: {exc.reason}") from exc
