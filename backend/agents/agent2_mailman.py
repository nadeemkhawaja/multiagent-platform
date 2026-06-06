import os
import json
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


async def scan_inbox(service, max_results=10):
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
    """Apply Mailman/* category labels and star key/urgent emails via Gmail API."""
    for email in processed_emails:
        msg_id = email.get('id')
        if not msg_id:
            continue
        add_labels = []
        cat = email['category']
        if cat in label_ids:
            add_labels.append(label_ids[cat])
        if email['is_key'] or cat == 'Urgent':
            add_labels.append('STARRED')
        if not add_labels:
            continue
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
        f"{', '.join(CATEGORIES)}. Write a one-sentence English summary. "
        'Return ONLY a JSON array: [{"i":<index>,"category":"<one category>","summary":"<one English sentence>"}].\n\n'
        f"{listing}"
    )
    result = await generate_json(prompt, system_prompt="You are an email triage assistant. Return only a JSON array.",
                                 agent_id="mailman", use_cache=False)

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


def build_summary_html(processed_emails, breakdown):
    key_alerts = [e for e in processed_emails if e['is_key'] or e['category'].lower() == 'urgent']
    return f"""
    <html><head><style>
      body {{ font-family:'Segoe UI',sans-serif; background:#0f172a; color:#f8fafc; padding:20px; }}
      .container {{ max-width:600px; margin:0 auto; }}
      h1 {{ color:#60a5fa; }} h2 {{ color:#94a3b8; border-bottom:1px solid #334155; padding-bottom:8px; }}
      .badge {{ display:inline-block; background:#1e293b; padding:4px 12px; border-radius:16px; margin:4px; font-size:.9em; }}
      .email-item {{ padding:12px; background:#1e293b; border-radius:8px; margin-bottom:8px; }}
      .email-item .subject {{ color:#f8fafc; font-weight:bold; }}
      .email-item .sender {{ color:#94a3b8; font-size:.85em; }}
      .email-item .summary {{ color:#cbd5e1; font-size:.9em; margin-top:4px; font-style:italic; }}
      .alert {{ border-left:3px solid #ef4444; }}
    </style></head><body><div class="container">
      <h1>✉️ Mailman Daily Summary</h1>
      <p style="color:#94a3b8;">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>
      <h2>📊 Category Breakdown</h2>
      <div>{''.join(f'<span class="badge">{c}: {n}</span>' for c, n in breakdown.items())}</div>
      {'<h2>🚨 Key Alerts</h2>' + ''.join(f'''<div class="email-item alert">
        <div class="subject">{e['subject']} ⭐</div><div class="sender">{e['sender']}</div>
        <div class="summary">{e['ai_summary']}</div></div>''' for e in key_alerts) if key_alerts else ''}
      <h2>📋 All Emails</h2>
      {''.join(f'''<div class="email-item"><div class="subject">[{e['category']}] {e['subject']}</div>
        <div class="sender">{e['sender']}</div><div class="summary">{e['ai_summary']}</div></div>'''
        for e in processed_emails)}
    </div></body></html>
    """


def send_daily_summary_email(processed_emails, breakdown):
    if not DAILY_DIGEST_EMAIL:
        return
    send_html_email(DAILY_DIGEST_EMAIL, "Mailman Daily Email Summary",
                    build_summary_html(processed_emails, breakdown))


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
        processed_emails = await classify_and_process_emails(emails, active_key_people)

        label_ids = await ensure_labels(service)
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
        print(f"[Mailman] Done — {len(processed_emails)} emails classified, labeled, and starred")
    except asyncio.CancelledError:
        orchestrator.update_agent_status("mailman", "idle")
        print("[Mailman] Job was manually cancelled.")
        raise
    except Exception as e:
        orchestrator.update_agent_status("mailman", "error", str(e))
