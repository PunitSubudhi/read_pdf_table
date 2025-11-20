import streamlit as st

st.title("Test App")
st.write("If you see this, Streamlit is working!")

try:
    from main import BankStatementParser
    st.success("Successfully imported BankStatementParser")
except Exception as e:
    st.error(f"Failed to import: {e}")
