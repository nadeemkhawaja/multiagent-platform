"""
Email rendering/logging utility.

Real email sending has been removed from this platform. Agents still call
send_html_email() to produce their digest, but it only logs the HTML to
backend/email_logs/ instead of dispatching anything over SMTP.
"""
import html
import os
from datetime import datetime


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


def send_html_email(to_email: str, subject: str, html_body: str, sender_name: str = "Multi-Agent Platform") -> bool:
    """Sending is disabled. Logs the rendered digest to backend/email_logs/ instead."""
    _log_email(to_email, subject, html_body)
    return False


# Keep the recent digests and drop the rest. One file per agent run with nothing
# pruning them reached 615 files / 4.2 MB, none of which anything reads after the
# day it was written.
MAX_EMAIL_LOGS = 200


def _prune_email_logs(log_dir: str, keep: int = MAX_EMAIL_LOGS):
    """Trim the digest directory to the newest `keep` files.

    Filenames are timestamp-prefixed, so lexical order is chronological order.
    """
    try:
        files = sorted(f for f in os.listdir(log_dir) if f.endswith(".html"))
        for stale in files[:max(0, len(files) - keep)]:
            try:
                os.remove(os.path.join(log_dir, stale))
            except OSError:
                pass
    except OSError:
        pass


def _log_email(to_email: str, subject: str, html_body: str):
    """Log email to file instead of sending it."""
    log_dir = os.path.join(os.path.dirname(__file__), "email_logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(log_dir, f"{timestamp}_{subject[:30].replace(' ', '_')}.html")

    with open(filename, "w") as f:
        f.write(f"<!-- To: {to_email} -->\n")
        f.write(f"<!-- Subject: {subject} -->\n")
        f.write(html_body)

    _prune_email_logs(log_dir)
    print(f"[EmailUtil] Sending disabled. Digest logged to {filename}")
