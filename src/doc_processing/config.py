"""Central configuration for document processing."""

from pathlib import Path

# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]

# Put your PDF in the project root next to main.py and set the file name here.
PDF_PATH = BASE_DIR / "sample.pdf"

ASSET_ROOT_SUFFIX = "_doc_assets"
DOCLING_ASSET_FOLDER = "docling_assets"

PAGE_MD_FOLDER = "pages_md"
PAGE_IMAGE_FOLDER = "page_images"
PICTURE_IMAGE_FOLDER = "image_png_images"
TABLE_IMAGE_FOLDER = "table_images"
FORMULA_IMAGE_FOLDER = "formula_images"

STITCHED_MARKDOWN_FILE = "stitched_raw_docling_markdown.md"
TABLE_CONTINUITY_JSON_FILE = "table_continuity_map.json"

PAGE_SEPARATOR_TEMPLATE = "\n\n--- PAGE {page_no} ---\n\n"

# -----------------------------------------------------------------------------
# Docling settings
# -----------------------------------------------------------------------------
IMAGES_SCALE = 1.6

# Placeholder used only in raw Docling markdown export. No replacement happens in Phase 1.
IMAGE_PLACEHOLDER = "[[DOCLING_IMAGE]]"

# -----------------------------------------------------------------------------
# Table detection tuning - deterministic / no LLM
# -----------------------------------------------------------------------------
MIN_TABLE_LINES = 2
MIN_TABLE_COLUMNS = 2
TOP_LINE_RATIO = 0.25
BOTTOM_LINE_RATIO = 0.75
CONTINUITY_THRESHOLD = 4.0

# Keep the production table-continuity JSON small.
# If True, only multi-page continued tables are written to the final JSON.
ONLY_WRITE_MULTI_PAGE_TABLES = True
