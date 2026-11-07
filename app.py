import streamlit as st
import pandas as pd
import io

st.set_page_config(
    page_title="Email Marketing Tool",
    layout="wide"
)

st.title("Email Marketing Tool")
st.write("B2B Lead Management System")

st.header("Import Leads")

uploaded_file = st.file_uploader(
    "Upload your CSV file",
    type=["csv"]
)

if uploaded_file:

    try:
        raw_data = uploaded_file.getvalue()

        # Handle different CSV encodings
        for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
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
        else:
            st.error("Unable to read this CSV file.")
            st.stop()

        # Clean column names
        df.columns = df.columns.str.strip()

        st.success("Leads uploaded successfully!")

        total_leads = len(df)

        if "Email" in df.columns:
            df["Email"] = df["Email"].str.strip()
            duplicate_emails = df["Email"].duplicated().sum()
        else:
            duplicate_emails = 0
            st.warning("No 'Email' column found.")

        col1, col2, col3 = st.columns(3)

        col1.metric("Total Leads", total_leads)
        col2.metric("Duplicate Emails", duplicate_emails)
        col3.metric(
            "Unique Leads",
            total_leads - duplicate_emails
        )

        st.subheader("Lead Preview")

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

    except Exception as e:
        st.error(f"Error processing file: {e}")

else:
    st.info("Upload a CSV file to get started.")
