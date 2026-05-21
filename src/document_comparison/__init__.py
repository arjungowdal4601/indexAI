"""Document comparison / gap analysis package."""

from .graph import run_document_comparison
from .schemas import ComparisonRunOutput

__all__ = ["ComparisonRunOutput", "run_document_comparison"]
