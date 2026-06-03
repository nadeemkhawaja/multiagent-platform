import os
import json
import base64
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from database import SessionLocal, AgentData
from llm_client import generate_completion
from orchestrator import orchestrator

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

async def authenticate_gmail():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("Missing credentials.json for Gmail OAuth")
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
        prompt = f"Classify this email. Subject: {email['subject']}. Snippet: {email['snippet']}. Categories: Urgent, Action Required, Follow-Up, Newsletter, Notification, Personal, Other. Output only the category name."
        category = await generate_completion(prompt, system_prompt="You are an email classifier.")
        category = category.strip()
        
        # Apply labels based on classification (Mocked for safety, would create/apply labels in reality)
        # service.users().messages().modify(userId='me', id=email['id'], body={'addLabelIds': [category_label_id]}).execute()
        
        # Determine if it's from a key person
        key_people = ["boss@company.com", "vip@example.com"]
        is_key = any(kp in email['sender'].lower() for kp in key_people)
        
        if is_key or category == "Urgent":
            # Apply star
            service.users().messages().modify(userId='me', id=email['id'], body={'addLabelIds': ['STARRED']}).execute()
            
        processed.append({
            "subject": email['subject'],
            "sender": email['sender'],
            "category": category,
            "is_key": is_key,
            "snippet": email['snippet']
        })
    return processed

async def mailman_job():
    orchestrator.update_agent_status("mailman", "running")
    try:
        creds = await authenticate_gmail()
        if not creds:
            orchestrator.update_agent_status("mailman", "error", "Missing Credentials")
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
        
        orchestrator.update_agent_status("mailman", "idle")
    except Exception as e:
        orchestrator.update_agent_status("mailman", "error", str(e))
