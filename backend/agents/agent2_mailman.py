import os
import json
import html
import asyncio
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from database import SessionLocal, AgentData, get_config
from llm_client import generate_json
from orchestrator import orchestrator
from email_utils import send_html_email

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")
CATEGORIES = ["Urgent", "Action Required", "Follow-Up", "Newsletter", "Notification", "Personal", "Other"]


def _key_people(override=None):
    if override:
        return [p.strip() for p in override.split(",") if p.strip()]
    cfg = get_config("key_people", os.getenv("KEY_PEOPLE", ""))
    return [p.strip() for p in str(cfg).split(",") if p.strip()]


def _authenticate_gmail_sync():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("[Mailman] Missing credentials.json for Gmail OAuth")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds


async def authenticate_gmail():
    return await asyncio.to_thread(_authenticate_gmail_sync)


def _scan_inbox_sync(service, max_results=10):
    """Synchronous Gmail fetch (googleapiclient is sync, one blocking call per message)
    — called via asyncio.to_thread so the event loop stays free and WebSocket status
    updates keep flowing while the scan is in progress."""
    results = service.users().messages().list(userId='me', labelIds=['INBOX'], maxResults=max_results).execute()
    messages = results.get('messages', [])
    email_data = []
    for msg in messages:
        full = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        headers = full.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
        email_data.append({"id": msg['id'], "subject": subject, "sender": sender,
                           "snippet": full.get('snippet', '')})
    return email_data


async def scan_inbox(service, max_results=10):
    return await asyncio.to_thread(_scan_inbox_sync, service, max_results)


async def ensure_labels(service) -> dict:
    """Return category → Gmail label ID, creating Mailman/* labels as needed."""
    def _list():
        return service.users().labels().list(userId='me').execute().get('labels', [])

    existing = await asyncio.to_thread(_list)
    label_map = {l['name']: l['id'] for l in existing}
    result = {}
    for cat in CATEGORIES:
        label_name = f"Mailman/{cat}"
        if label_name not in label_map:
            def _create(n=label_name):
                body = {'name': n, 'labelListVisibility': 'labelShow', 'messageListVisibility': 'show'}
                return service.users().labels().create(userId='me', body=body).execute()
            new_label = await asyncio.to_thread(_create)
            result[cat] = new_label['id']
        else:
            result[cat] = label_map[label_name]
    return result


async def apply_labels_and_stars(service, processed_emails, label_ids):
    """Star + label only Urgent or key-person mail — the 'alert on key people'
    set — so Mailman doesn't tag every routine email in the user's real inbox."""
    for email in processed_emails:
        msg_id = email.get('id')
        cat = email['category']
        if not msg_id or not (email['is_key'] or cat == 'Urgent'):
            continue
        add_labels = ['STARRED']
        if cat in label_ids:
            add_labels.append(label_ids[cat])
        def _modify(mid=msg_id, al=add_labels):
            return service.users().messages().modify(
                userId='me', id=mid, body={'addLabelIds': al, 'removeLabelIds': []}
            ).execute()
        await asyncio.to_thread(_modify)


async def classify_and_process_emails(emails, active_key_people):
    """One batched LLM call classifies + summarizes all emails (in English)."""
    if not emails:
        return []

    listing = "\n".join(
        f"[{i}] From: {e['sender']} | Subject: {e['subject']} | Preview: {e['snippet'][:200]}"
        for i, e in enumerate(emails)
    )
    prompt = (
        "Classify and summarize each email below. For EACH, choose exactly one category from: "
        f"{', '.join(CATEGORIES)}. "
        "Summary rule: a crisp gist of at most 12 words — what it is and any action needed. "
        "Plain and direct, no filler, do not start with 'This email' or 'The sender'. "
        'Return ONLY a JSON array: [{"i":<index>,"category":"<one category>","summary":"<<=12 words>"}].\n\n'
        f"{listing}"
    )
    # Isolate the LLM call — a failure here shouldn't prevent the scan from being
    # saved; emails simply fall back to category "Other" with no AI summary below.
    result = None
    try:
        result = await generate_json(prompt, system_prompt="You are an email triage assistant. Return only a JSON array.",
                                     agent_id="mailman", use_cache=False)
    except Exception as e:
        print(f"[Mailman] Classification LLM failed: {e}")

    by_index = {}
    if isinstance(result, list):
        for item in result:
            try:
                by_index[int(item.get("i"))] = item
            except (TypeError, ValueError):
                continue

    processed = []
    for i, email in enumerate(emails):
        info = by_index.get(i, {})
        category = str(info.get("category", "Other")).strip().strip('"').strip("'")
        if category not in CATEGORIES:
            category = "Other"
        ai_summary = str(info.get("summary", "")).strip()
        is_key = any(kp.lower() in email['sender'].lower() for kp in active_key_people)

        processed.append({"id": email['id'], "subject": email['subject'], "sender": email['sender'],
                          "category": category, "is_key": is_key, "snippet": email['snippet'],
                          "ai_summary": ai_summary})
    return processed


# Category → accent colour for the light-theme email (readable on white).
CAT_COLORS = {
    "Urgent": "#dc2626", "Action Required": "#ea580c", "Follow-Up": "#7c3aed",
    "Newsletter": "#2563eb", "Notification": "#64748b", "Personal": "#0d9488", "Other": "#94a3b8",
}


def _esc(s):
    return html.escape(str(s or ""))


def _cat_tag(cat):
    c = CAT_COLORS.get(cat, "#64748b")
    return (f'<span style="font-size:10px;font-weight:700;color:{c};background:#f1f5f9;'
            f'border:1px solid #e2e8f0;padding:2px 8px;border-radius:5px;white-space:nowrap">{_esc(cat)}</span>')


def build_summary_html(processed_emails, breakdown):
    key_alerts = [e for e in processed_emails if e['is_key'] or e['category'].lower() == 'urgent']

    chips = "".join(
        f'<span style="display:inline-block;font-size:12px;font-weight:600;color:'
        f'{CAT_COLORS.get(c, "#64748b")};background:#f1f5f9;border:1px solid #e2e8f0;'
        f'padding:5px 11px;border-radius:14px;margin:0 6px 6px 0">{_esc(c)} · {n}</span>'
        for c, n in breakdown.items()
    ) or '<span style="color:#94a3b8;font-size:13px">No emails this scan.</span>'

    alerts_html = ""
    if key_alerts:
        rows = "".join(
            f'''<div style="border:1px solid #fecaca;border-left:4px solid #dc2626;background:#fef2f2;
                  border-radius:8px;padding:12px 14px;margin-bottom:8px">
              <div style="font-weight:700;color:#0f172a;font-size:14px">⭐ {_esc(e['subject'])}</div>
              <div style="color:#64748b;font-size:12px;margin-top:2px">{_esc(e['sender'])}</div>
              {f'<div style="color:#334155;font-size:13px;margin-top:6px;line-height:1.45">{_esc(e["ai_summary"])}</div>' if e.get('ai_summary') else ''}
            </div>''' for e in key_alerts
        )
        alerts_html = (f'<h2 style="color:#334155;font-size:15px;border-bottom:1px solid #e2e8f0;'
                       f'padding-bottom:6px;margin:24px 0 12px">🚨 Key Alerts</h2>{rows}')

    list_rows = "".join(
        f'''<div style="padding:10px 0;border-bottom:1px solid #eef2f7">
          <div style="font-size:13px;font-weight:600;color:#0f172a">{_cat_tag(e['category'])}
            <span style="margin-left:7px">{_esc(e['subject'])}</span></div>
          {f'<div style="color:#475569;font-size:12.5px;margin-top:3px">{_esc(e["ai_summary"])}</div>' if e.get('ai_summary') else ''}
        </div>''' for e in processed_emails
    ) or '<p style="color:#94a3b8;font-size:13px">Inbox is clear.</p>'

    return f"""
    <html>
      <head>
        <meta name="color-scheme" content="light">
        <meta name="supported-color-schemes" content="light">
      </head>
      <body style="font-family:'Segoe UI',Arial,sans-serif;background:#eef2f7;color:#0f172a;padding:20px;margin:0">
        <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:28px">
          <h1 style="color:#2563eb;font-size:22px;margin:0 0 4px">✉️ Mailman Daily Summary</h1>
          <p style="color:#64748b;font-size:12px;margin:0 0 20px">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>
          <h2 style="color:#334155;font-size:15px;border-bottom:1px solid #e2e8f0;padding-bottom:6px;margin:0 0 12px">📊 Category Breakdown</h2>
          <div>{chips}</div>
          {alerts_html}
          <h2 style="color:#334155;font-size:15px;border-bottom:1px solid #e2e8f0;padding-bottom:6px;margin:24px 0 12px">📋 All Emails</h2>
          {list_rows}
        </div>
      </body>
    </html>
    """


def send_daily_summary_email(processed_emails, breakdown):
    if not DAILY_DIGEST_EMAIL:
        return
    send_html_email(DAILY_DIGEST_EMAIL, "Mailman Daily Email Summary",
                    build_summary_html(processed_emails, breakdown),
                    sender_name="Mailman Agent")


def email_preview() -> str:
    db = SessionLocal()
    rec = db.query(AgentData).filter_by(agent_name="mailman", key="emails").first()
    db.close()
    data = json.loads(rec.value) if rec else {"breakdown": {}, "emails": []}
    return build_summary_html(data.get("emails", []), data.get("breakdown", {}))


async def mailman_job(key_people_override: str = None, send_email: bool = True):
    orchestrator.update_agent_status("mailman", "running")
    try:
        active_key_people = _key_people(key_people_override)
        creds = await authenticate_gmail()
        if not creds:
            orchestrator.update_agent_status("mailman", "error", "Missing Gmail Credentials")
            return

        service = build('gmail', 'v1', credentials=creds)
        emails = await scan_inbox(service)

        # Classification (LLM, serialized via the semaphore) and label setup (Gmail
        # API, off-thread) are independent — run them concurrently.
        processed_emails, label_ids = await asyncio.gather(
            classify_and_process_emails(emails, active_key_people),
            ensure_labels(service),
        )
        await apply_labels_and_stars(service, processed_emails, label_ids)

        breakdown = {}
        for e in processed_emails:
            breakdown[e['category']] = breakdown.get(e['category'], 0) + 1

        db = SessionLocal()
        existing = db.query(AgentData).filter_by(agent_name="mailman", key="emails").first()
        val = json.dumps({"breakdown": breakdown, "emails": processed_emails})
        if existing:
            existing.value = val
        else:
            db.add(AgentData(agent_name="mailman", key="emails", value=val))
        db.commit()
        db.close()

        if send_email:
            send_daily_summary_email(processed_emails, breakdown)

        orchestrator.update_agent_status("mailman", "idle")
        flagged = sum(1 for e in processed_emails if e['is_key'] or e['category'] == 'Urgent')
        print(f"[Mailman] Done — {len(processed_emails)} emails classified, {flagged} starred/labeled (urgent or key-person)")
    except asyncio.CancelledError:
        orchestrator.update_agent_status("mailman", "idle")
        print("[Mailman] Job was manually cancelled.")
        raise
    except Exception as e:
        orchestrator.update_agent_status("mailman", "error", str(e))
