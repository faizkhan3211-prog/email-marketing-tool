import streamlit as st
import pandas as pd
import io

st.set_page_config(
    page_title="Email Marketing Tool",
    page_icon="📧",
    layout="wide"
)

st.title("📧 Email Marketing Tool")
st.subheader("B2B Lead Management System")

# -------------------------------
# MICROSOFT OUTLOOK CONNECTION
# -------------------------------

st.markdown("## Connect Your Email Account")

try:
    microsoft_configured = (
        "auth" in st.secrets
        and "microsoft" in st.secrets["auth"]
    )
except Exception:
    microsoft_configured = False

if not microsoft_configured:
    st.info(
        "Microsoft OAuth setup is not complete yet. "
        "Complete the Microsoft registration and Streamlit secrets setup."
    )
else:
    try:
        if st.user.is_logged_in:
            microsoft_email = (
                st.user.get("preferred_username")
                or st.user.get("email")
                or st.user.get("name")
                or "Microsoft account"
            )

            st.success(f"Connected with Microsoft: {microsoft_email}")

            if st.button("Disconnect Microsoft Account"):
                st.logout()

        else:
            if st.button(
                "🔵 Connect with Hotmail / Outlook",
                use_container_width=True
            ):
                st.login("microsoft")

    except Exception as e:
        st.error(f"Microsoft connection error: {e}")

st.divider()

# -------------------------------
# CSV LEAD UPLOAD
# -------------------------------

st.header("Import Leads")

uploaded_file = st.file_uploader(
    "Upload your CSV file",
    type=["csv"]
)

if uploaded_file is not None:

    try:
        file_bytes = uploaded_file.getvalue()

        df = None
        last_error = None

        for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
            try:
                df = pd.read_csv(
                    io.BytesIO(file_bytes),
                    encoding=encoding,
                    dtype=str,
                    keep_default_na=False
                )
                break
            except Exception as e:
                last_error = e

        if df is None:
            st.error(f"Could not read CSV: {last_error}")
            st.stop()

        df.columns = df.columns.astype(str).str.strip()

        st.success("CSV uploaded successfully!")

        email_columns = [
            col for col in df.columns
            if col.strip().lower() in ["email", "email address", "e-mail"]
        ]

        if email_columns:
            email_col = email_columns[0]

            emails = (
                df[email_col]
                .astype(str)
                .str.strip()
                .str.lower()
            )

            valid_emails = emails[emails != ""]

            duplicate_count = int(
                valid_emails.duplicated().sum()
            )

            unique_count = int(
                valid_emails.nunique()
            )
        else:
            duplicate_count = 0
            unique_count = len(df)

        col1, col2, col3 = st.columns(3)

        col1.metric("Total Leads", len(df))
        col2.metric("Duplicate Emails", duplicate_count)
        col3.metric("Unique Leads", unique_count)

        st.subheader("Lead Preview")
        st.dataframe(df, use_container_width=True)

        csv_data = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download Clean CSV",
            data=csv_data,
            file_name="clean_leads.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.error(f"Upload error: {e}")

else:
    st.info("Upload a CSV file to manage your leads.")
