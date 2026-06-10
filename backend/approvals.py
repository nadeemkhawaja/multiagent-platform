"""
Human-in-the-loop approval primitive.

Any agent can park an action for sign-off instead of executing it:

    approvals.request("mailman", kind="send_email", title=subject, payload={...})

The user approves or denies from the dashboard/API; approving dispatches the
action handler registered for that kind. Handlers are registered by the module
that owns the side effect (e.g. email_utils registers "send_email"), keeping
this module dependency-free.
"""
import json
from datetime import datetime

import database
from database import Approval

_ACTIONS = {}


def register_action(kind: str, handler):
    """handler(payload: dict) — executed when an approval of this kind is approved."""
    _ACTIONS[kind] = handler


def _notify(message: str, color: str):
    try:
        from orchestrator import orchestrator
        orchestrator.log_event(message, color)
    except Exception:
        pass


def _row_to_dict(row: Approval) -> dict:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "kind": row.kind,
        "title": row.title,
        "payload": json.loads(row.payload) if row.payload else None,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def request(agent_id: str, kind: str, title: str, payload: dict = None) -> int:
    """Queue an action for approval. Returns the approval id."""
    db = database.SessionLocal()
    try:
        row = Approval(agent_id=agent_id, kind=kind, title=title,
                       payload=json.dumps(payload) if payload else None)
        db.add(row)
        db.commit()
        approval_id = row.id
    finally:
        db.close()
    _notify(f"⏸ Approval requested · {title}", "#f59e0b")
    return approval_id


def list_approvals(status: str = None, k: int = 50) -> list:
    db = database.SessionLocal()
    try:
        q = db.query(Approval)
        if status:
            q = q.filter_by(status=status)
        rows = q.order_by(Approval.created_at.desc(), Approval.id.desc()).limit(k).all()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def get(approval_id: int):
    db = database.SessionLocal()
    try:
        row = db.query(Approval).get(approval_id)
        return _row_to_dict(row) if row else None
    finally:
        db.close()


def decide(approval_id: int, approved: bool, note: str = None) -> dict:
    """Resolve a pending approval. Approving runs the registered action handler;
    the decision is recorded even if the handler fails (see action_error)."""
    db = database.SessionLocal()
    try:
        row = db.query(Approval).get(approval_id)
        if not row:
            return {"error": f"approval {approval_id} not found"}
        if row.status != "pending":
            return {"error": f"approval {approval_id} already {row.status}"}
        row.status = "approved" if approved else "denied"
        row.note = note
        row.decided_at = datetime.utcnow()
        db.commit()
        result = _row_to_dict(row)
    finally:
        db.close()

    if approved:
        handler = _ACTIONS.get(result["kind"])
        if not handler:
            result["action"] = "no_handler"
        else:
            try:
                handler(result["payload"] or {})
                result["action"] = "executed"
            except Exception as e:
                result["action_error"] = str(e)
        _notify(f"✓ Approved · {result['title']}", "#16a34a")
    else:
        _notify(f"✕ Denied · {result['title']}", "#e5484d")
    return result
