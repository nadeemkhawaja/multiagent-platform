"""
Shared email utility using Gmail API (OAuth 2.0) or SMTP fallback.
All agents use this to send real HTML emails.

Because every agent sends through here, this is also the human-in-the-loop
gate: with the "require_email_approval" setting on, emails are queued as
pending approvals instead of sent, and go out only when approved from the
dashboard/API.
"""
import os
import html
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

import approvals

load_dotenv()


def bullets_to_html(text: str, color: str = "#334155") -> str:
    """Render bullet commentary (newline- or •-separated) as a real HTML list.

    LLM commentary comes back as "• a\\n• b\\n• c", but raw newlines collapse to a
    single line inside an HTML <p>, which is why the email digests looked like one
    run-on sentence while the app (which uses white-space:pre-line) showed bullets.
    This splits on newlines *and* inline bullet chars and emits a clean <ul>.
    Also tolerates a Python list or a stringified list ("['a', 'b']")."""
    if not text:
        return ""
    if isinstance(text, (list, tuple)):
        text = "\n".join(str(x) for x in text)
    else:
        text = str(text).strip()
        if text[:1] in "[(" and text[-1:] in ")]":
            import ast
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, (list, tuple)):
                    text = "\n".join(str(x) for x in parsed)
            except (ValueError, SyntaxError):
                pass
    lines = []
    for raw in str(text).replace("•", "\n").splitlines():
        s = raw.strip().lstrip("•-*").strip()
        if s:
            lines.append(s)
    if not lines:
        return ""
    items = "".join(
        f'<li style="margin:0 0 5px;line-height:1.5">{html.escape(s)}</li>' for s in lines
    )
    return f'<ul style="margin:0;padding-left:20px;color:{color};font-size:13px">{items}</ul>'

SMTP_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD", "")


def _approval_required() -> bool:
    """Email approval is opt-in (default off → agents send autonomously), and
    demo mode hard-bypasses it so a graded run can never stall on a human."""
    try:
        from database import get_config
        if get_config("demo_mode", False):
            return False
        return bool(get_config("require_email_approval", False))
    except Exception:
        return False


def send_html_email(to_email: str, subject: str, html_body: str, sender_name: str = "Multi-Agent Platform") -> bool:
    """
    Sends an HTML email via Gmail SMTP — or, when email approval is enabled,
    queues it for sign-off instead.
    Requires SMTP_APP_PASSWORD set in .env (a Gmail App Password).
    Falls back to logging if credentials are missing.
    """
    if _approval_required():
        approval_id = approvals.request(
            sender_name, kind="send_email", title=f"Email: {subject}",
            payload={"to_email": to_email, "subject": subject,
                     "html_body": html_body, "sender_name": sender_name},
        )
        print(f"[EmailUtil] queued for approval (#{approval_id}): {subject}")
        return True

    return _send_now(to_email, subject, html_body, sender_name)


def _send_now(to_email: str, subject: str, html_body: str, sender_name: str = "Multi-Agent Platform") -> bool:
    if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        print(f"[EmailUtil] SMTP credentials not configured. Would send to {to_email}: {subject}")
        _log_email(to_email, subject, html_body)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f'"{sender_name}" <{SMTP_EMAIL}>'
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


# Approving a queued email executes the real send (bypassing the gate).
approvals.register_action(
    "send_email",
    lambda p: _send_now(p["to_email"], p["subject"], p["html_body"],
                        p.get("sender_name", "Multi-Agent Platform")),
)
