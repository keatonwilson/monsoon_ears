"""NL→SQL query tab — POST a question, render the generated SQL + result rows."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient, APIClientError


def render(client: APIClient) -> None:
    st.subheader("Ask Monsoon Ears")
    st.caption(
        "Plain-English questions about the events store. Haiku rewrites your "
        "question into a SELECT; the API rejects anything that isn't a single "
        "read-only query over the allowed tables."
    )

    suggestions = [
        "Show me the last 10 EMS dispatches",
        "Which APRS stations reported rainfall in the last hour?",
        "Count events by transmission_type in the last 24 hours",
        "List monsoon-digest alerts from this week",
    ]
    with st.expander("💡 Suggestions", expanded=False):
        for s in suggestions:
            st.code(s, language="text")

    question = st.text_input(
        "Question",
        placeholder="e.g. show me cardiac calls in the last 24 hours",
        key="nl_question",
    )

    if not question or len(question.strip()) < 3:
        return

    if st.button("Run query", type="primary"):
        try:
            with st.spinner("Asking Haiku…"):
                result = client.nl_query(question)
        except APIClientError as exc:
            st.error(f"Query rejected: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            st.error(f"API error: {exc}")
            return

        st.markdown("**Generated SQL**")
        st.code(result["sql"], language="sql")
        if result["row_count"] == 0:
            st.info("Query ran successfully but returned no rows.")
            return
        df = pd.DataFrame(result["rows"])
        st.caption(f"{result['row_count']} row(s)")
        st.dataframe(df, use_container_width=True, hide_index=True)
