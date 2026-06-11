"""Shared HTTP fetch with UA + retry — replaces the per-agent httpx boilerplate."""
import asyncio

import httpx

from .registry import tool

UA = {"User-Agent": "Mozilla/5.0 (MultiAgentPlatform/1.0)"}


@tool("web.fetch_json", "GET a URL and return the parsed JSON body, with retries.")
async def fetch_json(url: str, timeout: float = 15.0, retries: int = 2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=UA) as client:
                r = await client.get(url)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_err
