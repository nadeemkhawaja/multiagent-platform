"""Tests for ws.ConnectionManager — no real network sockets required.
Run from the backend directory:  python -m pytest -q
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ws import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail_on_send=False):
        self.accepted = False
        self.sent = []
        self.fail_on_send = fail_on_send

    async def accept(self):
        self.accepted = True

    async def send_text(self, msg):
        if self.fail_on_send:
            raise RuntimeError("connection closed")
        self.sent.append(msg)


def test_connect_accepts_and_registers():
    mgr = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(mgr.connect(ws))
    assert ws.accepted
    assert ws in mgr.active


def test_broadcast_sends_json_to_all_connections():
    mgr = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    asyncio.run(mgr.connect(ws1))
    asyncio.run(mgr.connect(ws2))
    asyncio.run(mgr.broadcast({"type": "state", "data": {"x": 1}}))
    assert json.loads(ws1.sent[0]) == {"type": "state", "data": {"x": 1}}
    assert json.loads(ws2.sent[0]) == {"type": "state", "data": {"x": 1}}


def test_broadcast_drops_dead_connections():
    mgr = ConnectionManager()
    good, bad = FakeWebSocket(), FakeWebSocket(fail_on_send=True)
    asyncio.run(mgr.connect(good))
    asyncio.run(mgr.connect(bad))
    asyncio.run(mgr.broadcast({"type": "ping"}))
    assert bad not in mgr.active
    assert good in mgr.active
    assert len(good.sent) == 1


def test_broadcast_with_no_connections_is_noop():
    mgr = ConnectionManager()
    asyncio.run(mgr.broadcast({"type": "ping"}))  # must not raise


def test_disconnect_removes_connection():
    mgr = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(mgr.connect(ws))
    mgr.disconnect(ws)
    assert ws not in mgr.active


def test_disconnect_unknown_connection_is_noop():
    mgr = ConnectionManager()
    ws = FakeWebSocket()
    mgr.disconnect(ws)  # must not raise
