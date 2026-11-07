import streamlit as st

st.title("Email Marketing Tool")
st.header("Connect Your Email Account")

# Gmail
if st.button("📧 Connect with Gmail", use_container_width=True):
    st.login("google")

# Outlook / Hotmail
if st.button("📨 Connect with Hotmail / Outlook", use_container_width=True):
    st.login("microsoft")

# Company Email
st.divider()
st.subheader("Connect with Company Email")

with st.form("smtp_connection"):
    email = st.text_input("Business Email")
    username = st.text_input("SMTP Username")
    server = st.text_input("SMTP Server")
    port = st.number_input("SMTP Port", value=587)
    security = st.selectbox(
        "Connection Security",
        ["STARTTLS", "SSL"]
    )
    password = st.text_input(
        "Password / App Password",
        type="password"
    )

    connect = st.form_submit_button("Connect Company Email")

    if connect:
        st.info("SMTP connection test will be added here.")
