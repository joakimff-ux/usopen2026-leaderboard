"""Admin authentication via Streamlit session state."""

from __future__ import annotations

import streamlit as st


def is_admin() -> bool:
    return bool(st.session_state.get("is_admin"))


def login_admin(password: str) -> bool:
    expected = st.secrets.get("ADMIN_PASSWORD", "")
    if not expected:
        return False
    if password == expected:
        st.session_state["is_admin"] = True
        return True
    return False


def logout_admin() -> None:
    st.session_state.pop("is_admin", None)


def require_admin() -> bool:
    if is_admin():
        return True
    st.warning("Admin access required. Log in from the Admin page.")
    return False
