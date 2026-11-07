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

    microsoft_issuer = "login.microsoftonline.com" in issuer
    microsoft_issuer = microsoft_issuer or "sts.windows.net" in issuer
    if microsoft_issuer:
        return "microsoft"

    return None

def current_access_token() -> str | None:
    """Read the explicitly exposed access token; never display or log it."""
    try:
        token = st.user.tokens["access"]
        return str(token) if token else None
    except Exception:
        return None


def current_account_email(provider: str | None = None) -> str:
    data = current_user_data()
    if provider == "microsoft":
        return str(data.get("preferred_username") or data.get("email") or "").strip()
    return str(data.get("email") or data.get("preferred_username") or "").strip()


def oauth_provider_is_configured(provider: str) -> bool:
    auth = secret_section("auth")
    config = auth.get(provider, {})
    if not isinstance(config, dict):
        try:
            config = dict(config)
        except Exception:
            return False
    return bool(config.get("client_id") and config.get("client_secret") and config.get("server_metadata_url"))


# -----------------------------------------------------------------------------
# SMTP helpers
# -----------------------------------------------------------------------------
def smtp_connect_and_test(config: dict) -> None:
    """Authenticate to SMTP to verify the settings. No email is sent here."""
    host = config["host"]
    port = int(config["port"])
    security_mode = config["security"]
    username = config["username"]
    password = config["password"]

    if security_mode == "SSL / TLS":
        with smtplib.SMTP_SSL(
            host,
            port,
            timeout=25,
            context=ssl.create_default_context(),
        ) as smtp:
            smtp.login(username, password)
            code, message = smtp.noop()
    else:
        with smtplib.SMTP(host, port, timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(username, password)
            code, message = smtp.noop()

    if code >= 400:
        raise RuntimeError(f"SMTP server test failed ({code}): {message!r}")


def send_smtp_email(config: dict, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config["email"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    host = config["host"]
    port = int(config["port"])
    if config["security"] == "SSL / TLS":
        with smtplib.SMTP_SSL(
            host,
            port,
            timeout=30,
            context=ssl.create_default_context(),
        ) as smtp:
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)


# -----------------------------------------------------------------------------
# Gmail API and Microsoft Graph sending helpers
# -----------------------------------------------------------------------------
def send_gmail_api_email(access_token: str, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    response = requests.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw_message},
        timeout=30,
    )

    if response.status_code not in (200,):
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except Exception:
            detail = response.text[:500]

        if response.status_code == 401:
            raise RuntimeError("Gmail access token expired or invalid. Disconnect Gmail and connect again.")
        if response.status_code == 403:
            raise RuntimeError(
                "Gmail denied sending. Check that Gmail API is enabled and the account granted "
                "the gmail.send permission. Google Workspace administrators may also restrict access. "
                + detail
            )
        raise RuntimeError(f"Gmail API error {response.status_code}: {detail}")


def send_microsoft_graph_email(access_token: str, recipient: str, subject: str, body: str) -> None:
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        },
        "saveToSentItems": True,
    }

    response = requests.post(
        "https://graph.microsoft.com/v1.0/me/sendMail",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if response.status_code == 202:
        return

    detail = ""
    try:
        detail = response.json().get("error", {}).get("message", "")
    except Exception:
        detail = response.text[:500]

    if response.status_code == 401:
        raise RuntimeError("Microsoft access token expired or invalid. Disconnect Outlook and connect again.")
    if response.status_code == 403:
        raise RuntimeError(
            "Microsoft Graph denied sending. Check that delegated Mail.Send permission is added "
            "and consented for this account. " + detail
        )
    raise RuntimeError(f"Microsoft Graph error {response.status_code}: {detail}")


# -----------------------------------------------------------------------------
# CSV, validation, suppression, and personalization
# -----------------------------------------------------------------------------
def read_uploaded_csv(file_bytes: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return pd.read_csv(
                io.BytesIO(file_bytes),
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                on_bad_lines="error",
            )
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not read this CSV file: {last_error}")


def valid_email(value: Any) -> bool:
    return bool(EMAIL_PATTERN.match(str(value or "").strip()))


def personalize(template: str, row: pd.Series) -> str:
    values = {str(key).strip().lower(): str(value) for key, value in row.items()}

    def replace_match(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        return values.get(key, match.group(0))

    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace_match, template)


def extract_placeholders(template: str) -> list[str]:
    return re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", template)


# -----------------------------------------------------------------------------
# Page header and connection area
# -----------------------------------------------------------------------------
st.title("✉️ Email Marketing Tool")
st.caption("Connect a sender, import your contacts, personalize your message, preview it, and send.")

with st.expander("Important: sending limits and safe use", expanded=False):
    st.write(
        "Use this tool only for people who have opted in or whom you are otherwise legally "
        "permitted to contact. Respect opt-outs and provider rules. This starter app sends "
        "individual messages, limits each batch to 25 recipients, and does not provide an "
        "unsubscribe database, open tracking, bounce handling, or scheduled campaigns."
    )

st.header("1. Connect your email account")

provider = current_oauth_provider()
access_token = current_access_token() if provider else None
account_email = current_account_email(provider) if provider else ""

if provider and access_token:
    provider_label = "Gmail / Google Workspace" if provider == "google" else "Outlook / Hotmail / Microsoft 365"
    st.success(f"Connected with {provider_label}: {account_email or 'account connected'}")
    st.caption("OAuth access is active for this session. If sending later returns an expired-token error, reconnect this account.")
    if st.button("Disconnect / switch Google or Microsoft account", key="disconnect_oauth"):
        st.logout()
elif provider and not access_token:
    st.warning(
        "You are signed in, but no API access token is available. Check that [auth] "
        "expose_tokens = [\"id\", \"access\"] is present in Streamlit Secrets, "
        "and that the provider scope includes the send permission."
    )
    if st.button("Disconnect this account", key="disconnect_no_token"):
        st.logout()
else:
    col1, col2 = st.columns(2)
    with col1:
        google_ready = oauth_provider_is_configured("google")
        if st.button(
            "🔵 Connect with Gmail / Google Workspace",
            use_container_width=True,
            disabled=not google_ready,
            key="connect_google",
        ):
            st.login("google")
        if not google_ready:
            st.caption("Google OAuth credentials are missing from Streamlit Secrets.")
    with col2:
        microsoft_ready = oauth_provider_is_configured("microsoft")
        if st.button(
            "🟦 Connect with Hotmail / Outlook / Microsoft 365",
            use_container_width=True,
            disabled=not microsoft_ready,
            key="connect_microsoft",
        ):
            st.login("microsoft")
        if not microsoft_ready:
            st.caption("Microsoft OAuth credentials are missing from Streamlit Secrets.")

st.markdown("#### Connect Zoho Mail or another company email (SMTP)")
with st.expander("Open SMTP connection settings", expanded=False):
    st.caption(
        "SMTP credentials are held in this Streamlit session only. They are not written to GitHub "
        "or Streamlit Secrets. Disconnect SMTP before leaving a shared computer."
    )

    smtp_provider = st.selectbox(
        "Email provider",
        ["Zoho Mail", "Other business email (SMTP)"],
        key="smtp_provider_choice",
    )

    if smtp_provider == "Zoho Mail":
        default_host = "smtp.zoho.com"
        default_port = 587
        default_security = "STARTTLS"
        st.info(
            "Zoho's paid domain mail may use smtppro.zoho.com or a region-specific server. "
            "Check the server configuration shown inside your Zoho Mail account and edit the host below if needed."
        )
    else:
        default_host = "mail.yourcompany.com"
        default_port = 587
        default_security = "STARTTLS"

    with st.form("smtp_connection_form"):
        smtp_email = st.text_input("Email address", placeholder="you@yourcompany.com")
        smtp_username = st.text_input("SMTP username", placeholder="Usually your full email address")
        smtp_host = st.text_input("SMTP server", value=default_host, key=f"smtp_host_{smtp_provider}")
        smtp_port = st.number_input("SMTP port", min_value=1, max_value=65535, value=default_port, step=1)
        smtp_security = st.selectbox(
            "Connection security",
            ["STARTTLS", "SSL / TLS"],
            index=0 if default_security == "STARTTLS" else 1,
        )
        smtp_password = st.text_input("Password / app password", type="password")
        smtp_submitted = st.form_submit_button("Test and connect SMTP", use_container_width=True)

    if smtp_submitted:
        if not valid_email(smtp_email):
            st.error("Please enter a valid sender email address.")
        elif not smtp_host.strip() or not smtp_username.strip() or not smtp_password:
            st.error("Please complete the SMTP server, username, and password fields.")
        else:
            candidate = {
                "email": smtp_email.strip(),
                "username": smtp_username.strip(),
                "host": smtp_host.strip(),
                "port": int(smtp_port),
                "security": "SSL / TLS" if smtp_security == "SSL / TLS" else "STARTTLS",
                "password": smtp_password,
            }
            try:
                smtp_connect_and_test(candidate)
                st.session_state["smtp_config"] = candidate
                st.success(f"SMTP connected successfully: {candidate['email']}")
            except Exception as exc:
                st.error(f"SMTP connection failed: {exc}")

    if st.session_state.get("smtp_config"):
        active_smtp = st.session_state["smtp_config"]
        st.success(f"SMTP account connected: {active_smtp['email']}")
        if st.button("Disconnect SMTP account", key="disconnect_smtp"):
            st.session_state.pop("smtp_config", None)
            st.rerun()

# Build the list of available send methods. OAuth API tokens are read from st.user, not stored in code.
send_methods: dict[str, dict] = {}
if provider == "google" and access_token:
    send_methods[f"Gmail / Google Workspace — {account_email or 'connected account'}"] = {
        "type": "google",
        "token": access_token,
        "email": account_email,
    }
elif provider == "microsoft" and access_token:
    send_methods[f"Outlook / Microsoft 365 — {account_email or 'connected account'}"] = {
        "type": "microsoft",
        "token": access_token,
        "email": account_email,
    }

if st.session_state.get("smtp_config"):
    smtp_config_for_send = st.session_state["smtp_config"]
    send_methods[f"SMTP — {smtp_config_for_send['email']}"] = {
        "type": "smtp",
        "config": smtp_config_for_send,
        "email": smtp_config_for_send["email"],
    }

if send_methods:
    st.success("At least one sending account is ready.")
else:
    st.info("Connect Gmail, Outlook, Zoho, or another company SMTP account before sending.")

st.divider()

# -----------------------------------------------------------------------------
# Import CSV and choose recipients
# -----------------------------------------------------------------------------
st.header("2. Import and select recipients")
uploaded_file = st.file_uploader("Upload your contacts CSV", type=["csv"])

if uploaded_file is None:
    st.info("Upload a CSV file containing an email column to continue.")
    st.stop()

try:
    raw_df = read_uploaded_csv(uploaded_file.getvalue())
except Exception as exc:
    st.error(str(exc))
    st.stop()

if raw_df.empty or len(raw_df.columns) == 0:
    st.error("The uploaded CSV is empty.")
    st.stop()

raw_df.columns = [str(col).strip() for col in raw_df.columns]
if len(set(raw_df.columns)) != len(raw_df.columns):
    st.error("Your CSV contains duplicate column names. Rename the duplicate columns and upload it again.")
    st.stop()

email_candidates = [
    col for col in raw_df.columns
    if col.strip().lower() in {"email", "email address", "e-mail", "business email", "work email"}
]
email_col_default = email_candidates[0] if email_candidates else raw_df.columns[0]
email_col = st.selectbox(
    "Which column contains the recipient email addresses?",
    list(raw_df.columns),
    index=list(raw_df.columns).index(email_col_default),
)

contacts = raw_df.copy()
contacts[email_col] = contacts[email_col].astype(str).str.strip()
contacts = contacts[contacts[email_col].apply(valid_email)].copy()
contacts["__normalized_email"] = contacts[email_col].str.lower()
contacts = contacts.drop_duplicates(subset="__normalized_email", keep="first")
contacts = contacts.drop(columns=["__normalized_email"]).reset_index(drop=True)

suppression_text = st.text_area(
    "Suppression list (optional): emails separated by commas or new lines; these will not be sent",
    height=80,
    placeholder="unsubscribed@example.com\nno-contact@example.com",
)
suppressed = {
    item.strip().lower()
    for item in re.split(r"[\s,;]+", suppression_text)
    if valid_email(item.strip())
}
if suppressed:
    contacts = contacts[~contacts[email_col].str.lower().isin(suppressed)].reset_index(drop=True)

metric1, metric2, metric3 = st.columns(3)
metric1.metric("CSV rows", len(raw_df))
metric2.metric("Valid unique recipients", len(contacts))
metric3.metric("Suppressed emails", len(suppressed))

if contacts.empty:
    st.warning("No valid recipients remain after validation and suppression filtering.")
    st.stop()

select_all = st.checkbox("Select all remaining recipients", value=False, key="select_all_recipients")
editor_df = contacts.copy()
editor_df.insert(0, "__send__", bool(select_all))
disabled_columns = [col for col in editor_df.columns if col != "__send__"]
edited_contacts = st.data_editor(
    editor_df,
    use_container_width=True,
    hide_index=True,
    disabled=disabled_columns,
    key=f"recipient_selection_editor_{int(select_all)}",
    column_config={
        "__send__": st.column_config.CheckboxColumn(
            "Send?",
            help="Tick only the contacts you intend to email.",
            default=False,
        )
    },
)
selected_contacts = edited_contacts[edited_contacts["__send__"] == True].drop(columns=["__send__"])  # noqa: E712
st.write(f"**Selected recipients:** {len(selected_contacts)}")

st.divider()

# -----------------------------------------------------------------------------
# Compose, preview, and send
# -----------------------------------------------------------------------------
st.header("3. Compose and send")
if not send_methods:
    st.warning("Connect a sender account above before composing a campaign.")
    st.stop()

sending_account_label = st.selectbox("Send from", list(send_methods.keys()))
sending_account = send_methods[sending_account_label]

subject = st.text_input("Email subject", placeholder="A quick question about {{Company}}")
body_template = st.text_area(
    "Email message",
    height=240,
    placeholder="Hi {{First Name}},\n\nI wanted to reach out about...\n\nBest,\nYour Name",
)
st.caption("Personalization format: {{Column Name}}. The name inside braces must match a CSV column header.")

placeholders = extract_placeholders(subject + "\n" + body_template)
column_lookup = {str(col).strip().lower() for col in contacts.columns}
unknown_placeholders = sorted({p for p in placeholders if p.strip().lower() not in column_lookup})
if unknown_placeholders:
    st.warning("These personalization fields do not match CSV columns and will remain unchanged: " + ", ".join(unknown_placeholders))

if len(selected_contacts) > 0:
    preview_row = selected_contacts.iloc[0]
    with st.expander("Preview the first selected email", expanded=True):
        st.write("**To:**", preview_row[email_col])
        st.write("**Subject:**", personalize(subject, preview_row))
        st.text(personalize(body_template, preview_row))

st.warning(
    f"This version sends up to {MAX_EMAILS_PER_BATCH} individually addressed emails per batch, "
    "with a short delay between messages. It does not send one shared bulk To/Cc message."
)
consent_confirmed = st.checkbox(
    "I confirm these recipients have opted in or that I have another lawful basis to contact them, and I will honor all opt-outs.",
    value=False,
)

send_col, test_col = st.columns(2)
with test_col:
    test_recipient = sending_account.get("email", "")
    test_disabled = not valid_email(test_recipient) or not subject.strip() or not body_template.strip()
    test_clicked = st.button("Send test email to my connected address", disabled=test_disabled, use_container_width=True)

with send_col:
    batch_disabled = (
        len(selected_contacts) == 0
        or len(selected_contacts) > MAX_EMAILS_PER_BATCH
        or not subject.strip()
        or not body_template.strip()
        or not consent_confirmed
    )
    send_clicked = st.button(
        f"Send to {len(selected_contacts)} selected recipients",
        type="primary",
        disabled=batch_disabled,
        use_container_width=True,
    )


def deliver_one(recipient: str, rendered_subject: str, rendered_body: str) -> None:
    method_type = sending_account["type"]
    if method_type == "google":
        send_gmail_api_email(sending_account["token"], recipient, rendered_subject, rendered_body)
    elif method_type == "microsoft":
        send_microsoft_graph_email(sending_account["token"], recipient, rendered_subject, rendered_body)
    elif method_type == "smtp":
        send_smtp_email(sending_account["config"], recipient, rendered_subject, rendered_body)
    else:
        raise RuntimeError("Unknown sending provider.")


if test_clicked:
    try:
        test_subject = "[TEST] " + personalize(subject, selected_contacts.iloc[0] if len(selected_contacts) else contacts.iloc[0])
        test_body = personalize(body_template, selected_contacts.iloc[0] if len(selected_contacts) else contacts.iloc[0])
        deliver_one(test_recipient, test_subject, test_body)
        st.success(f"Test email sent to {test_recipient}.")
    except Exception as exc:
        st.error(f"Test email failed: {exc}")


if send_clicked:
    if len(selected_contacts) > MAX_EMAILS_PER_BATCH:
        st.error(f"Select no more than {MAX_EMAILS_PER_BATCH} recipients per batch.")
    else:
        progress = st.progress(0)
        status = st.empty()
        results = []
        total = len(selected_contacts)

        stop_for_reauthorization = False
        for index, (_, row) in enumerate(selected_contacts.iterrows(), start=1):
            recipient = str(row[email_col]).strip()
            rendered_subject = personalize(subject, row)
            rendered_body = personalize(body_template, row)

            try:
                deliver_one(recipient, rendered_subject, rendered_body)
                results.append({"Recipient": recipient, "Status": "Sent", "Details": "Accepted by sending provider"})
            except Exception as exc:
                error_detail = str(exc)[:500]
                results.append({"Recipient": recipient, "Status": "Failed", "Details": error_detail})
                if "access token expired" in error_detail.lower():
                    stop_for_reauthorization = True

            progress.progress(index / total)
            status.write(f"Processed {index} of {total}: {recipient}")

            if stop_for_reauthorization:
                for _, remaining_row in list(selected_contacts.iterrows())[index:]:
                    results.append({
                        "Recipient": str(remaining_row[email_col]).strip(),
                        "Status": "Not attempted",
                        "Details": "Stopped because the OAuth access token needs to be renewed.",
                    })
                break

            if index < total:
                time.sleep(SEND_DELAY_SECONDS)

        results_df = pd.DataFrame(results)
        sent_count = int((results_df["Status"] == "Sent").sum())
        failed_count = int((results_df["Status"] == "Failed").sum())
        st.subheader("Batch result")
        result1, result2 = st.columns(2)
        result1.metric("Accepted by provider", sent_count)
        result2.metric("Failed", failed_count)
        st.dataframe(results_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download sending report CSV",
            data=results_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="email_sending_report.csv",
            mime="text/csv",
        )

st.divider()
st.caption(
    "Security note: OAuth client secrets belong only in Streamlit Secrets. SMTP passwords stay in the current app session and are not saved to GitHub. "
    "OAuth access tokens can expire; reconnect the sender if the provider returns an expired-token error."
)
