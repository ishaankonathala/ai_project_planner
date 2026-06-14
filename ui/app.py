"""Streamlit shell for the AXIOM HTML UI (see axiom.html)."""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="AXIOM — AI Project Planner",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Hide all Streamlit chrome so the HTML page fills the viewport
st.markdown(
    """
    <style>
    /* Remove Streamlit header, footer, and default padding */
    #MainMenu, header, footer { visibility: hidden; height: 0 }
    .block-container { padding: 0 !important; max-width: 100% !important }
    [data-testid="stAppViewContainer"] { padding: 0 }
    [data-testid="stVerticalBlock"] > div { padding: 0 !important }
    iframe[title="streamlit_app"] { border: none !important }
    </style>
    """,
    unsafe_allow_html=True,
)

_html_path = Path(__file__).resolve().parent / "axiom.html"
if not _html_path.is_file():
    st.error(f"Missing UI file: {_html_path}")
    st.stop()

_html = _html_path.read_text(encoding="utf-8")

components.html(_html, height=900, scrolling=True)
