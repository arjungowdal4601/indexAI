"""Standalone runner for the document processing pipeline."""

from __future__ import annotations

from .pipeline import run_document_processing


def main() -> None:
    run_document_processing()


if __name__ == "__main__":
    main()
