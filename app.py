"""Compatibility notice for the legacy retrieval demo.

The active framework UI is ``frontend/streamlit_app.py``. The old standalone
vectorless retrieval demo has moved to ``legacy/vectorless_retrieval_demo_app.py``.
"""

from __future__ import annotations


def main() -> int:
    print("Active UI: streamlit run frontend/streamlit_app.py")
    print("Legacy retrieval demo: streamlit run legacy/vectorless_retrieval_demo_app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
