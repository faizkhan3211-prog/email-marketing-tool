import base64
import hmac
import io
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any

import pandas as pd
import requests
import streamlit as st


# -----------------------------------------------------------------------------
# App configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Email Marketing Tool",
    page_icon="✉️",
    layout="wide",
)

APP_TITLE = "Email Marketing Tool"
MAX_EMAILS_PER_BATCH = 25
SEND_DELAY_SECONDS = 1.0
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# -----------------------------------------------------------------------------
# Secrets and access protection
# -----------------------------------------------------------------------------
def secret_section(name: str) -> dict:
    """Return a secrets section as a plain dictionary, or an empty dictionary."""
    try:
        value = st.secrets[name]
        return dict(value)
    except Exception:
        return {}


def app_password_gate() -> None:
    """Require a private app password so a public Streamlit URL is not open to anyone."""
    app_secrets = secret_section("app")
    expected_password = str(app_secrets.get("access_password", "")).strip()

    if not expected_password:
        st.error(
            "App is locked until you add an access password in Streamlit Cloud "
            "Settings → Secrets. Add [app] access_password = \"a-long-random-password\"."
        )
        st.stop()

    if st.session_state.get("app_unlocked", False):
        return

    st.title("🔐 Private access")
    st.caption("Enter your private app password to open the email tool.")
    with st.form("app_password_form"):
        entered = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Unlock app", use_container_width=True)

    if submitted:
        if hmac.compare_digest(entered, expected_password):
            st.session_state["app_unlocked"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
    st.stop()


app_password_gate()


# -----------------------------------------------------------------------------
# Identity provider and token helpers
# -----------------------------------------------------------------------------
def current_user_data() -> dict:
    try:
        return st.user.to_dict()
    except Exception:
        try:
            return dict(st.user)
        except Exception:
            return {}


def current_oauth_provider() -> str | None:
    """Identify the currently signed-in OIDC provider from its issuer claim."""
    data = current_user_data()
    issuer = str(data.get("iss", "")).lower()

    if "accounts.google.com" in issuer:
        return "google"
    if "login.microsoftonline.com" in issuer or "sts.windows.net" in issuer:
