"""Tests for approvals.py and the email approval gate in email_utils.py.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import approvals
import email_utils


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point database.py's engine/SessionLocal at a fresh temp SQLite file."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    return database


# ── request / list / get ─────────────────────────────────────────────────────
def test_request_creates_pending_approval(db):
    aid = approvals.request("wolf", "send_email", "Email: Daily Brief", {"to_email": "a@b.c"})
    row = approvals.get(aid)
    assert row["status"] == "pending"
    assert row["agent_id"] == "wolf"
    assert row["payload"] == {"to_email": "a@b.c"}
    assert row["decided_at"] is None


def test_list_filters_by_status(db):
    approvals.request("wolf", "send_email", "one")
    aid = approvals.request("wolf", "send_email", "two")
    approvals.decide(aid, approved=False)

    assert [a["title"] for a in approvals.list_approvals(status="pending")] == ["one"]
    assert [a["title"] for a in approvals.list_approvals(status="denied")] == ["two"]
    assert len(approvals.list_approvals()) == 2


def test_get_unknown_returns_none(db):
    assert approvals.get(999) is None


# ── decide ───────────────────────────────────────────────────────────────────
def test_approve_executes_registered_action(db, monkeypatch):
    executed = {}
    monkeypatch.setitem(approvals._ACTIONS, "test_kind", lambda p: executed.update(p))

    aid = approvals.request("wolf", "test_kind", "do it", {"x": 1})
    out = approvals.decide(aid, approved=True, note="lgtm")
    assert out["status"] == "approved"
    assert out["action"] == "executed"
    assert out["note"] == "lgtm"
    assert executed == {"x": 1}


def test_deny_does_not_execute_action(db, monkeypatch):
    executed = {}
    monkeypatch.setitem(approvals._ACTIONS, "test_kind", lambda p: executed.update(p))

    aid = approvals.request("wolf", "test_kind", "do it", {"x": 1})
    out = approvals.decide(aid, approved=False)
    assert out["status"] == "denied"
    assert executed == {}


def test_decide_twice_returns_error(db):
    aid = approvals.request("wolf", "send_email", "once")
    approvals.decide(aid, approved=False)
    out = approvals.decide(aid, approved=True)
    assert "already denied" in out["error"]


def test_decide_unknown_id_returns_error(db):
    assert "not found" in approvals.decide(12345, approved=True)["error"]


def test_action_failure_is_reported_but_decision_stands(db, monkeypatch):
    def boom(payload):
        raise RuntimeError("smtp down")
    monkeypatch.setitem(approvals._ACTIONS, "test_kind", boom)

    aid = approvals.request("wolf", "test_kind", "fragile")
    out = approvals.decide(aid, approved=True)
    assert out["status"] == "approved"
    assert "smtp down" in out["action_error"]
    assert approvals.get(aid)["status"] == "approved"


def test_approve_without_handler_reports_no_handler(db):
    aid = approvals.request("wolf", "unknown_kind", "orphan")
    assert approvals.decide(aid, approved=True)["action"] == "no_handler"


# ── email gate ───────────────────────────────────────────────────────────────
def test_email_gate_queues_instead_of_sending(db, monkeypatch):
    database.set_config("require_email_approval", True)
    sent = {}
    monkeypatch.setattr(email_utils, "_send_now", lambda *a, **kw: sent.update({"args": a}) or True)

    ok = email_utils.send_html_email("to@x.com", "Gated Subject", "<p>hi</p>", sender_name="Wolf")
    assert ok is True
    assert sent == {}   # nothing sent yet

    pending = approvals.list_approvals(status="pending")
    assert len(pending) == 1
    assert pending[0]["title"] == "Email: Gated Subject"
    assert pending[0]["agent_id"] == "Wolf"
    assert pending[0]["payload"]["to_email"] == "to@x.com"


def test_email_gate_approval_sends_the_email(db, monkeypatch):
    database.set_config("require_email_approval", True)
    sent = {}

    def fake_send(to_email, subject, html_body, sender_name="Multi-Agent Platform"):
        sent.update({"to": to_email, "subject": subject, "html": html_body, "from": sender_name})
        return True
    monkeypatch.setattr(email_utils, "_send_now", fake_send)

    email_utils.send_html_email("to@x.com", "Approved Subject", "<p>body</p>", sender_name="Wolf")
    aid = approvals.list_approvals(status="pending")[0]["id"]
    out = approvals.decide(aid, approved=True)

    assert out["action"] == "executed"
    assert sent == {"to": "to@x.com", "subject": "Approved Subject",
                    "html": "<p>body</p>", "from": "Wolf"}


def test_email_gate_off_sends_directly(db, monkeypatch):
    database.set_config("require_email_approval", False)
    sent = {}
    monkeypatch.setattr(email_utils, "_send_now", lambda *a, **kw: sent.update({"a": a}) or True)

    email_utils.send_html_email("to@x.com", "Direct", "<p>x</p>")
    assert sent
    assert approvals.list_approvals() == []
