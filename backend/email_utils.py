"""
Shared email utility using Gmail API (OAuth 2.0) or SMTP fallback.
All agents use this to send real HTML emails.
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD", "")


def send_html_email(to_email: str, subject: str, html_body: str) -> bool:
    """
    Sends an HTML email via Gmail SMTP.
    Requires SMTP_APP_PASSWORD set in .env (a Gmail App Password).
    Falls back to logging if credentials are missing.
    """
    if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        print(f"[EmailUtil] SMTP credentials not configured. Would send to {to_email}: {subject}")
        _log_email(to_email, subject, html_body)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email

        msg.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, msg.as_string())

        print(f"[EmailUtil] Email sent successfully to {to_email}: {subject}")
        return True

    except Exception as e:
        print(f"[EmailUtil] Failed to send email: {e}")
        _log_email(to_email, subject, html_body)
        return False


def _log_email(to_email: str, subject: str, html_body: str):
    """Log email to file as fallback when SMTP is not configured."""
    log_dir = os.path.join(os.path.dirname(__file__), "email_logs")
    os.makedirs(log_dir, exist_ok=True)
    
    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(log_dir, f"{timestamp}_{subject[:30].replace(' ', '_')}.html")
    
    with open(filename, "w") as f:
        f.write(f"<!-- To: {to_email} -->\n")
        f.write(f"<!-- Subject: {subject} -->\n")
        f.write(html_body)
    
    print(f"[EmailUtil] Email logged to {filename}")
