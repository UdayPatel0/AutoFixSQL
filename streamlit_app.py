"""
streamlit_app.py — Minimal AutoFixSQL UI: text input for a natural
language... well for now, a raw SQL query -> Run button -> shows
original SQL, error (if any), repair steps, repaired SQL, and result.

This is a starting point for the "Streamlit UI — Basic Interface" task;
wire in NL->SQL generation later where marked below.

Run: streamlit run demo/streamlit_app.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
from src.pipeline import autofix

st.set_page_config(page_title="AutoFixSQL", layout="centered")
st.title("AutoFixSQL")
st.caption("Self-healing SQL: execute -> diagnose -> repair -> retry")

query = st.text_area("Enter a SQL query", height=100,
                      placeholder="SELECT * FROM studnts")
# TODO: swap the text_area above for an NL input box once LLM
# NL->SQL generation is wired in (see LLM Integration Research task).

if st.button("Run") and query.strip():
    with st.spinner("Running AutoFixSQL pipeline..."):
        output = autofix(query)

    if output["success"]:
        st.success(f"Succeeded after {output['attempts']} attempt(s)")
    else:
        st.error(output["safe_failure_message"] or "Query could not be repaired.")

    st.subheader("Final SQL")
    st.code(output["final_sql"], language="sql")

    if output["success"]:
        st.subheader("Result")
        st.write(output["columns"])
        st.dataframe(output["rows"])

    st.subheader("Repair trail")
    for step in output["repair_trail"]:
        label = f"Attempt {step['attempt']}"
        if step["diagnosis_category"]:
            label += f" — diagnosed as: {step['diagnosis_category']}"
        with st.expander(label):
            st.code(step["sql_tried"], language="sql")
            if step["error"]:
                st.write(f"Error: {step['error']}")
            if step["repaired_sql"]:
                st.write("Repaired to:")
                st.code(step["repaired_sql"], language="sql")
