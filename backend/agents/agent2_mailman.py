import os
import json
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator
from email_utils import send_html_email

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
DAILY_DIGEST_EMAIL = os.getenv("DAILY_DIGEST_EMAIL", "")

# Configurable key-people list
KEY_PEOPLE = os.getenv("KEY_PEOPLE", "").split(",") if os.getenv("KEY_PEOPLE") else []


async def authenticate_gmail():
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


async def scan_inbox(service):
    results = service.users().messages().list(userId='me', labelIds=['INBOX'], maxResults=10).execute()
    messages = results.get('messages', [])

    email_data = []
    for msg in messages:
        msg_full = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        headers = msg_full.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
        snippet = msg_full.get('snippet', '')

        email_data.append({
            "id": msg['id'],
            "subject": subject,
            "sender": sender,
            "snippet": snippet
        })
    return email_data


async def classify_and_process_emails(service, emails):
    processed = []
    for email in emails:
        # Step 1: Classify email with LLM
        classify_prompt = (
            f"Classify this email into exactly one category. "
            f"Subject: {email['subject']}. From: {email['sender']}. Preview: {email['snippet'][:200]}. "
            f"Categories: Urgent, Action Required, Follow-Up, Newsletter, Notification, Personal, Other. "
            f"Reply with ONLY the category name, nothing else."
        )
        category = await generate_completion(
            classify_prompt,
            system_prompt="You are an email classifier. Output only the category name."
        )
        category = category.strip().strip('"').strip("'")

        # Step 2: Generate AI summary with LLM
        summary_prompt = (
            f"Write a concise 1-sentence summary of this email. "
            f"Subject: {email['subject']}. From: {email['sender']}. Preview: {email['snippet'][:300]}. "
            f"Reply with only the summary sentence."
        )
        ai_summary = await generate_completion(
            summary_prompt,
            system_prompt="You are a concise email summarizer. Output only one sentence."
        )
        ai_summary = ai_summary.strip()

        # Step 3: Check if from key person
        is_key = any(kp.strip().lower() in email['sender'].lower() for kp in KEY_PEOPLE if kp.strip())

        # Step 4: Apply Gmail labels and stars
        try:
            if is_key or category.lower() in ["urgent", "action required"]:
                service.users().messages().modify(
                    userId='me',
                    id=email['id'],
                    body={'addLabelIds': ['STARRED']}
                ).execute()
        except Exception as e:
            print(f"[Mailman] Failed to apply label/star: {e}")

        processed.append({
            "subject": email['subject'],
            "sender": email['sender'],
            "category": category,
            "is_key": is_key,
            "snippet": email['snippet'],
            "ai_summary": ai_summary
        })
    return processed


def send_daily_summary_email(processed_emails, breakdown):
    """Sends a daily summary email with category breakdown and key alerts."""
    if not DAILY_DIGEST_EMAIL:
        return

    key_alerts = [e for e in processed_emails if e['is_key'] or e['category'].lower() == 'urgent']

    html_content = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }}
          .container {{ max-width: 600px; margin: 0 auto; }}
          h1 {{ color: #60a5fa; }}
          h2 {{ color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
          .badge {{ display: inline-block; background: #1e293b; padding: 4px 12px; border-radius: 16px; margin: 4px; font-size: 0.9em; }}
          .email-item {{ padding: 12px; background: #1e293b; border-radius: 8px; margin-bottom: 8px; }}
          .email-item .subject {{ color: #f8fafc; font-weight: bold; }}
          .email-item .sender {{ color: #94a3b8; font-size: 0.85em; }}
          .email-item .summary {{ color: #cbd5e1; font-size: 0.9em; margin-top: 4px; font-style: italic; }}
          .alert {{ border-left: 3px solid #ef4444; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h1>✉️ Mailman Daily Summary</h1>
          <p style="color:#94a3b8;">{datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}</p>

          <h2>📊 Category Breakdown</h2>
          <div>{''.join([f'<span class="badge">{cat}: {cnt}</span>' for cat, cnt in breakdown.items()])}</div>

          {'<h2>🚨 Key Alerts</h2>' + ''.join([f'''
          <div class="email-item alert">
            <div class="subject">{e['subject']} ⭐</div>
            <div class="sender">{e['sender']}</div>
            <div class="summary">{e['ai_summary']}</div>
          </div>''' for e in key_alerts]) if key_alerts else ''}

          <h2>📋 All Emails</h2>
          {''.join([f'''
          <div class="email-item">
            <div class="subject">[{e['category']}] {e['subject']}</div>
            <div class="sender">{e['sender']}</div>
            <div class="summary">{e['ai_summary']}</div>
          </div>''' for e in processed_emails])}
        </div>
      </body>
    </html>
    """

    send_html_email(DAILY_DIGEST_EMAIL, "Mailman Daily Email Summary", html_content)


async def mailman_job():
    orchestrator.update_agent_status("mailman", "running")
    try:
        creds = await authenticate_gmail()
        if not creds:
            orchestrator.update_agent_status("mailman", "error", "Missing Gmail Credentials")
            return

        service = build('gmail', 'v1', credentials=creds)
        emails = await scan_inbox(service)
        processed_emails = await classify_and_process_emails(service, emails)

        # Calculate breakdown
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

        # Send daily summary email
        send_daily_summary_email(processed_emails, breakdown)

        orchestrator.update_agent_status("mailman", "idle")
    except Exception as e:
        orchestrator.update_agent_status("mailman", "error", str(e))
