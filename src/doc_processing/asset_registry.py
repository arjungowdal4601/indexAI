"""Page-local asset registry for document processing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

PAGE_ASSET_REGISTRY_FILE = "page_asset_registry.json"
REGISTRY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AssetRecord:
    kind: str
    path: str
    source_page: int
    local_index: int
    global_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "source_page": self.source_page,
            "local_index": self.local_index,
            "global_index": self.global_index,
        }


def registry_path(docling_assets_dir: str | Path) -> Path:
    return Path(docling_assets_dir) / PAGE_ASSET_REGISTRY_FILE


def empty_registry() -> dict[str, Any]:
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "pages": []}


def load_page_asset_registry(docling_assets_dir: str | Path) -> dict[str, Any]:
    path = registry_path(docling_assets_dir)
    if not path.exists():
        raise FileNotFoundError(f"Page asset registry not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_page_asset_registry_if_exists(docling_assets_dir: str | Path) -> dict[str, Any]:
    path = registry_path(docling_assets_dir)
    if not path.exists():
        return empty_registry()
    return json.loads(path.read_text(encoding="utf-8"))


def page_entries_by_number(registry: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(page["page"]): page for page in registry.get("pages", [])}


def has_page_registry_entry(docling_assets_dir: str | Path, page_no: int) -> bool:
    registry = load_page_asset_registry_if_exists(docling_assets_dir)
    return int(page_no) in page_entries_by_number(registry)


def write_page_asset_registry(docling_assets_dir: str | Path, registry: dict[str, Any]) -> None:
    path = registry_path(docling_assets_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def upsert_page_registry_entry(docling_assets_dir: str | Path, page_entry: dict[str, Any]) -> None:
    registry = load_page_asset_registry_if_exists(docling_assets_dir)
    pages = [
        page
        for page in registry.get("pages", [])
        if int(page.get("page", -1)) != int(page_entry["page"])
    ]
    pages.append(page_entry)
    registry["schema_version"] = REGISTRY_SCHEMA_VERSION
    registry["pages"] = sorted(pages, key=lambda page: int(page["page"]))
    write_page_asset_registry(docling_assets_dir, registry)


def build_page_registry_entry(
    *,
    page_no: int,
    markdown_path: Path,
    docling_assets_dir: Path,
    markdown: str,
    assets: Iterable[AssetRecord],
) -> dict[str, Any]:
    counts = {"picture": 0, "table": 0, "formula": 0}
    asset_payloads: List[dict[str, Any]] = []

    for asset in assets:
        payload = asset.to_dict()
        counts[asset.kind] += 1
        asset_payloads.append(payload)

    return {
        "page": int(page_no),
        "markdown_path": markdown_path.relative_to(docling_assets_dir).as_posix(),
        "counts": counts,
        "assets": asset_payloads,
    }


def page_assets_by_kind(page_entry: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped = {"picture": [], "table": [], "formula": []}
    for asset in page_entry.get("assets", []):
        grouped.setdefault(asset["kind"], []).append(asset)
    for assets in grouped.values():
        assets.sort(key=lambda asset: int(asset["local_index"]))
    return grouped
