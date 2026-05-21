"""Entry point guidance for the separate retrieval demo."""

from __future__ import annotations

import streamlit as st

from frontend.ui_components import configure_page


def main() -> None:
    configure_page("Retrieval Demo")
    st.caption("The vectorless retrieval demo remains separate from the comparison product UI.")
    st.markdown(
        """
Run the existing retrieval demo from the project root:

```powershell
streamlit run app.py
```

That demo explains topic-index routing and page evidence. The comparison UI uses
the FastAPI backend and focuses on SOP-vs-regulatory gap review.
"""
    )


if __name__ == "__main__":
    main()
