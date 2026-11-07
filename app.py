
import streamlit as st
import pandas as pd

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
    df = pd.read_csv(uploaded_file)

    st.success("Leads uploaded successfully!")

    total_leads = len(df)
    duplicate_emails = 0

    if "Email" in df.columns:
        duplicate_emails = df["Email"].duplicated().sum()

    col1, col2, col3 = st.columns(3)

    col1.metric("Total Leads", total_leads)
    col2.metric("Duplicate Emails", duplicate_emails)
    col3.metric("Unique Leads", total_leads - duplicate_emails)

    st.subheader("Lead Preview")
    st.dataframe(df, use_container_width=True)

else:
    st.info("Upload a CSV file to get started.")
