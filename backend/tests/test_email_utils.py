"""Tests for email_utils.py — sending is disabled, everything logs to file.
Run from the backend directory:  python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_utils


def test_send_html_email_always_logs_instead_of_sending(monkeypatch, tmp_path):
    monkeypatch.setattr(email_utils, "__file__", str(tmp_path / "email_utils.py"))

    ok = email_utils.send_html_email("user@example.com", "Test Subject", "<p>hi</p>")
    assert ok is False

    files = list((tmp_path / "email_logs").glob("*.html"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "user@example.com" in content
    assert "Test Subject" in content
    assert "<p>hi</p>" in content
