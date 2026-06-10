"""Tests for email_utils.py — fallback logging path + SMTP success/failure paths.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_utils


def test_send_html_email_falls_back_to_log_when_no_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(email_utils, "SMTP_EMAIL", "")
    monkeypatch.setattr(email_utils, "SMTP_APP_PASSWORD", "")
    monkeypatch.setattr(email_utils, "__file__", str(tmp_path / "email_utils.py"))

    ok = email_utils.send_html_email("user@example.com", "Test Subject", "<p>hi</p>")
    assert ok is False

    files = list((tmp_path / "email_logs").glob("*.html"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "user@example.com" in content
    assert "Test Subject" in content
    assert "<p>hi</p>" in content


class FakeSMTP:
    instances = []

    def __init__(self, host, port, context=None):
        self.host = host
        self.port = port
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def sendmail(self, from_addr, to_addr, msg):
        self.sent = (from_addr, to_addr, msg)


def test_send_html_email_success_via_smtp(monkeypatch):
    monkeypatch.setattr(email_utils, "SMTP_EMAIL", "me@gmail.com")
    monkeypatch.setattr(email_utils, "SMTP_APP_PASSWORD", "app-password")
    FakeSMTP.instances.clear()
    monkeypatch.setattr(email_utils.smtplib, "SMTP_SSL", FakeSMTP)

    ok = email_utils.send_html_email("to@example.com", "Subject", "<p>body</p>", sender_name="Tester")
    assert ok is True
    sent = FakeSMTP.instances[0]
    assert sent.logged_in == ("me@gmail.com", "app-password")
    assert sent.sent[0] == "me@gmail.com"
    assert sent.sent[1] == "to@example.com"
    assert "Subject" in sent.sent[2]


def test_send_html_email_falls_back_to_log_on_smtp_error(monkeypatch, tmp_path):
    monkeypatch.setattr(email_utils, "SMTP_EMAIL", "me@gmail.com")
    monkeypatch.setattr(email_utils, "SMTP_APP_PASSWORD", "app-password")
    monkeypatch.setattr(email_utils, "__file__", str(tmp_path / "email_utils.py"))

    def boom(*a, **kw):
        raise OSError("network down")

    monkeypatch.setattr(email_utils.smtplib, "SMTP_SSL", boom)
    ok = email_utils.send_html_email("to@example.com", "Subject", "<p>body</p>")
    assert ok is False
    assert list((tmp_path / "email_logs").glob("*.html"))
