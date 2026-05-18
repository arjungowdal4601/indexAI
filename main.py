from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from doc_processing.pipeline import run_document_processing


def main() -> None:
    run_document_processing()


if __name__ == "__main__":
    main()
