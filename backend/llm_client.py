import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3")

# Global Semaphore to ensure only one agent calls the LLM at a time
llm_semaphore = asyncio.Semaphore(1)

async def generate_completion(prompt: str, system_prompt: str = "You are a helpful AI assistant.") -> str:
    """
    Calls the local LLM. Acquires the global semaphore first to prevent deadlocks.
    """
    async with llm_semaphore:
        async with httpx.AsyncClient() as client:
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            }
            try:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json=payload,
                    timeout=120.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("message", {}).get("content", "")
            except Exception as e:
                print(f"Error calling LLM: {e}")
                return f"Error: {e}"
