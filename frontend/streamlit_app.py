import pandas as pd
import streamlit as st
from utils import auto_chart

from api import ApiError, call_backend

st.set_page_config(page_title="AI BI Dashboard", layout="wide")

st.title("📊 AI Business Intelligence Dashboard")

question = st.text_input(
    "Ask a business question:",
    placeholder="e.g. What are the top 3 products by revenue?",
)
explain = st.checkbox("Explain the result", value=True)

if st.button("Run Query") and question:
    with st.spinner("Thinking..."):
        try:
            st.session_state["res"] = call_backend(question, explain=explain)
        except ApiError as e:
            st.session_state.pop("res", None)
            st.error(e.message)
            details = [
                f"code: {e.code}" if e.code else None,
                f"request id: {e.request_id}" if e.request_id else None,
            ]
            if any(details):
                st.caption(" · ".join(d for d in details if d))


if "res" in st.session_state:
    res = st.session_state["res"]

    df = pd.DataFrame(res["result"])

    # RESULTS TABLE SUMMARY
    st.subheader("📋 Results")
    st.caption("🧠 Generated SQL")
    st.code(res["sql"], language="sql")
    if res.get("truncated"):
        st.warning(
            f"Showing the first {res['row_count']} rows; the query matched more. "
            "Narrow the question to see the rest."
        )
    for assumption in res.get("assumptions") or []:
        st.info(f"Assumption: {assumption}")
    st.dataframe(df, use_container_width=True)

    # VISUALIZATION:
    fig = auto_chart(df)
    if fig:
        st.subheader("📈 Visualization")
        st.plotly_chart(fig, use_container_width=True)

    # EXPLANATION:
    if res.get("explanation"):
        st.subheader("💡 Explanation")
        st.write(res["explanation"])
