"""Artifact retention cleanup for processed documents."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from backend import config
from backend.services import document_service, registry


DOCUMENT_STANDARD_DELETE_PATHS = [
    "docling_assets/pages_md",
    "docling_assets/image_png_images",
    "docling_assets/table_images",
    "docling_assets/formula_images",
    "docling_assets/stitched_raw_docling_markdown.md",
    "docling_assets/table_continuity_map.json",
]

DOCUMENT_MINIMAL_DELETE_PATHS = [
    "indexing_output/processing_state.json",
    "indexing_output/validation_report.json",
    "indexing_output/revision_log.md",
    "indexing_output/backups",
]

def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _assert_within_root(root: Path, path: Path) -> None:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if path_resolved != root_resolved and root_resolved not in path_resolved.parents:
        raise ValueError(f"Refusing to delete path outside artifact root: {path}")


def _delete_path(root: Path, relative_path: str) -> str | None:
    target = root / relative_path
    if not target.exists():
        return None
    _assert_within_root(root, target)
    deleted = _relative_path(root, target)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return deleted


def _remove_empty_dir(path: Path) -> bool:
    if path.exists() and path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        return True
    return False


def _move_page_images_to_canonical_root(asset_root: Path, manifest: dict) -> list[str]:
    canonical = asset_root / "page_images"
    legacy = asset_root / "docling_assets" / "page_images"
    moved: list[str] = []

    if not canonical.exists() and legacy.exists():
        shutil.move(str(legacy), str(canonical))
        moved.append("docling_assets/page_images -> page_images")

    if canonical.exists():
        manifest["page_images_folder"] = "page_images"
    else:
        manifest.setdefault("page_images_folder", "docling_assets/page_images")

    return moved


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cleanup_document_artifacts(document_id: str) -> dict:
    document = document_service.get_document_or_404(document_id)
    asset_root = Path(document["asset_root"])
    manifest_path = document_service.manifest_path(document)
    manifest = document_service.load_manifest(document)
    mode = config.get_artifact_retention_mode()
    deleted: list[str] = []
    moved: list[str] = []

    if mode != "debug":
        moved.extend(_move_page_images_to_canonical_root(asset_root, manifest))
        delete_paths = list(DOCUMENT_STANDARD_DELETE_PATHS)
        if mode == "minimal":
            delete_paths.extend(DOCUMENT_MINIMAL_DELETE_PATHS)
        for relative_path in delete_paths:
            removed = _delete_path(asset_root, relative_path)
            if removed is not None:
                deleted.append(removed)
        if _remove_empty_dir(asset_root / "docling_assets"):
            deleted.append("docling_assets")

    manifest["artifact_retention_mode"] = mode
    manifest["cleanup_completed_at"] = registry.utc_now()
    manifest["deleted_artifacts"] = sorted(set(deleted))
    if moved:
        manifest["moved_artifacts"] = moved
    elif "moved_artifacts" in manifest:
        manifest["moved_artifacts"] = manifest.get("moved_artifacts") or []

    _write_json(manifest_path, manifest)
    return {
        "document_id": document_id,
        "mode": mode,
        "cleanup_completed_at": manifest["cleanup_completed_at"],
        "deleted": manifest["deleted_artifacts"],
        "moved": manifest.get("moved_artifacts", []),
    }
