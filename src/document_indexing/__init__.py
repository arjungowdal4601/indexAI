"""Topic-based document indexing agent."""

from .graph import run_document_indexing
from .schemas import IndexingOutput

__all__ = ["IndexingOutput", "run_document_indexing"]
