# backend/rag/llm/groq_httpx.py
from __future__ import annotations
from typing import Optional
import httpx
import asyncio

class GroqHTTPxLLM:
    """
    Minimal async LLM client that matches the .generate(prompt, ...) interface
    expected by the planner/synthesizer/controller.
    Uses the same Groq endpoint you already call in ChatbotAgent._call_llm_groq.
    """
    def __init__(self, api_key: str, model: str):
        if not api_key or not model:
            raise RuntimeError("GroqHTTPxLLM requires api_key and model.")
        self.api_key = api_key
        self.model = model
        self.url = "https://api.groq.com/openai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 900) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a careful, grounded assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.url, headers=self.headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
