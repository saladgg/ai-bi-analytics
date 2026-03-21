import streamlit as st
import pandas as pd
from api import call_backend
from utils import auto_chart

st.set_page_config(page_title="AI BI Dashboard", layout="wide")

st.title("📊 AI Business Intelligence Dashboard")

question = st.text_input(
    "Ask a business question:",
    placeholder="e.g. What are the top 3 products by revenue?"
)

if st.button("Run Query") and question:
    with st.spinner("Thinking..."):
        try:
            res = call_backend(question)
            st.session_state["res"] = res
        except Exception as e:
            st.error(str(e))


if "res" in st.session_state:
    res = st.session_state["res"]

    df = pd.DataFrame(res["result"])
    
    # RESULTS TABLE SUMMARY
    st.subheader("📋 Results")
    st.caption("🧠 Generated SQL")
    st.code(res["sql"], language="sql")
    st.dataframe(df, use_container_width=True)

    # VISUALIZATION:
    fig = auto_chart(df)
    if fig:
        st.subheader("📈 Visualization")
        st.plotly_chart(fig, use_container_width=True)
    
    # EXPLANATION:    
    st.subheader("💡 Explanation")
    st.write(res["explanation"])