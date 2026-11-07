
import streamlit as st
import pandas as pd
import io
import smtplib
import ssl

st.set_page_config(
    page_title="Email Marketing Tool",
    page_icon="📧",
    layout="wide"
)

# Session storage
if "email_accounts" not in st.session_state:
    st.session_state.email_accounts = []

st.title("📧 Email Marketing Tool")
st.caption("B2B Lead Management & Email Account Connections")

# --------------------------------
# EMAIL PROVIDER SETTINGS
# --------------------------------

PROVIDERS = {
    "Gmail": {
        "host": "smtp.gmail.com",
        "port": 465,
        "security": "SSL"
    },
    "Google Workspace": {
        "host": "smtp.gmail.com",
        "port": 465,
        "security": "SSL"
    },
    "Outlook / Microsoft 365": {
        "host": "smtp.office365.com",
        "port": 587,
        "security": "STARTTLS"
    },
    "Zoho Mail": {
        "host": "smtp.zoho.com",
        "port": 465,
        "security": "SSL"
    },
    "Other Business Email (SMTP)": {
        "host": "",
        "port": 465,
        "security": "SSL"
    }
}

# --------------------------------
# SIDEBAR
# --------------------------------

page = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Connect Email",
        "Lead Import"
    ]
)

# --------------------------------
# DASHBOARD
# --------------------------------

if page == "Dashboard":

    st.header("Dashboard")

    col1, col2 = st.columns(2)

    col1.metric(
        "Connected Email Accounts",
        len(st.session_state.email_accounts)
    )

    col2.metric(
        "Email Campaigns",
        0
    )

    st.subheader("Connected Accounts")

    if st.session_state.email_accounts:

        for account in st.session_state.email_accounts:

            st.write(
                f"📧 {account['email']} "
                f"({account['provider']})"
            )

    else:
        st.info("No email accounts connected yet.")

# --------------------------------
# CONNECT EMAIL
# --------------------------------

elif page == "Connect Email":

    st.header("Connect Your Email Account")

    st.write(
        "Select your email provider and enter "
        "your SMTP connection details."
    )

    provider = st.selectbox(
        "Select Email Provider",
        list(PROVIDERS.keys())
    )

    settings = PROVIDERS[provider]

    with st.form("email_connection_form"):

        email = st.text_input(
            "Email Address",
            placeholder="you@example.com"
        )

        username = st.text_input(
            "SMTP Username",
            placeholder="Usually your full email address"
        )

        smtp_host = st.text_input(
            "SMTP Server",
            value=settings["host"]
        )

        smtp_port = st.number_input(
            "SMTP Port",
            min_value=1,
            max_value=65535,
            value=settings["port"]
        )

        security = st.selectbox(
            "Connection Security",
            ["SSL", "STARTTLS"],
            index=0 if settings["security"] == "SSL" else 1
        )

        password = st.text_input(
            "Password / App Password",
            type="password"
        )

        submitted = st.form_submit_button(
            "Test Connection & Connect",
            use_container_width=True
        )

    if submitted:

        if not all([
            email.strip(),
            username.strip(),
            smtp_host.strip(),
            password
        ]):
            st.error("Please complete all required fields.")

        else:

            try:

                context = ssl.create_default_context()

                if security == "SSL":

                    server = smtplib.SMTP_SSL(
                        smtp_host.strip(),
                        int(smtp_port),
                        context=context,
                        timeout=20
                    )

                else:

                    server = smtplib.SMTP(
                        smtp_host.strip(),
                        int(smtp_port),
                        timeout=20
                    )

                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()

                server.login(
                    username.strip(),
                    password.replace(" ", "")
                )

                server.quit()

                # Save credentials in session only
                existing = [
                    a for a in st.session_state.email_accounts
                    if a["email"].lower() != email.strip().lower()
                ]

                existing.append({
                    "provider": provider,
                    "email": email.strip(),
                    "username": username.strip(),
                    "host": smtp_host.strip(),
                    "port": int(smtp_port),
                    "security": security,
                    "password": password.replace(" ", "")
                })

                st.session_state.email_accounts = existing

                st.success(
                    f"Successfully connected: {email}"
                )

            except Exception as e:

                st.error(
                    f"Connection failed: {str(e)}"
                )

    st.divider()

    st.subheader("Your Connected Accounts")

    if st.session_state.email_accounts:

        for i, account in enumerate(
            st.session_state.email_accounts
        ):

            col1, col2, col3 = st.columns([3, 2, 1])

            col1.write(f"📧 {account['email']}")
            col2.write(account["provider"])

            if col3.button("Remove", key=f"remove_{i}"):

                st.session_state.email_accounts.pop(i)
                st.rerun()

    else:

        st.info("Connect your first email account above.")

    st.caption(
        "Credentials are kept in Streamlit session memory only. "
        "They are not saved permanently."
    )

# --------------------------------
# LEAD IMPORT
# --------------------------------

elif page == "Lead Import":

    st.header("Import B2B Leads")

    uploaded_file = st.file_uploader(
        "Upload CSV File",
        type=["csv"]
    )

    if uploaded_file:

        try:

            raw_data = uploaded_file.getvalue()

            df = None

            for encoding in [
                "utf-8-sig",
                "utf-8",
                "cp1252",
                "latin1"
            ]:

                try:

                    df = pd.read_csv(
                        io.BytesIO(raw_data),
                        encoding=encoding,
                        dtype=str,
                        keep_default_na=False
                    )

                    break

                except UnicodeDecodeError:
                    continue

            if df is None:
                st.error("Unable to read CSV file.")
                st.stop()

            df.columns = df.columns.str.strip()

            st.success("Leads uploaded successfully!")

            total = len(df)

            if "Email" in df.columns:

                df["Email"] = df["Email"].str.strip()

                duplicates = (
                    df["Email"].str.lower()
                    .duplicated()
                    .sum()
                )

            else:

                duplicates = 0
                st.warning("Email column not found.")

            col1, col2, col3 = st.columns(3)

            col1.metric("Total Leads", total)
            col2.metric("Duplicate Emails", duplicates)
            col3.metric("Unique Leads", total - duplicates)

            st.subheader("Lead Preview")

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )

        except Exception as e:

            st.error(f"File processing error: {e}")
