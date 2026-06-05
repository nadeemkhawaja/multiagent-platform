"""WebSocket broadcaster — pushes orchestrator state to all connected dashboards."""
import asyncio
import json
from typing import Set


class ConnectionManager:
    def __init__(self):
        self.active: Set = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws):
        await ws.accept()
        async with self._lock:
            self.active.add(ws)

    def disconnect(self, ws):
        self.active.discard(ws)

    async def broadcast(self, payload: dict):
        if not self.active:
            return
        msg = json.dumps(payload, default=str)
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
