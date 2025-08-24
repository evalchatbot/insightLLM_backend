# backend/rag/llm/providers.py
from __future__ import annotations
import asyncio
from typing import Any
from backend.rag.config import get_rag_settings

class BaseLLM:
    async def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 900) -> str:
        raise NotImplementedError

class OpenAILLM(BaseLLM):
    def __init__(self, api_key: str | None):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError("openai package not installed. `pip install openai`") from e
        self._OpenAI = OpenAI
        self.client = OpenAI(api_key=api_key)

    async def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 900) -> str:
        # Use chat.completions for broad compatibility
        def _call():
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",  # fallback-friendly; change if you prefer
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        return await asyncio.to_thread(_call)

class GroqLLM(BaseLLM):
    def __init__(self, api_key: str | None):
        try:
            from groq import Groq  # type: ignore
        except Exception as e:
            raise RuntimeError("groq package not installed. `pip install groq`") from e
        self.client = Groq(api_key=api_key)

    async def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 900) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        return await asyncio.to_thread(_call)

def get_llm() -> BaseLLM:
    s = get_rag_settings()
    provider = (s.LLM_PROVIDER or "groq").lower()
    if provider == "openai":
        if not s.OPENAI_API_KEY:
            # OpenAI SDK can also read from env; we allow None here
            return OpenAILLM(api_key=s.OPENAI_API_KEY)
        return OpenAILLM(api_key=s.OPENAI_API_KEY)
    elif provider == "groq":
        if not s.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY not set")
        return GroqLLM(api_key=s.GROQ_API_KEY)
    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {s.LLM_PROVIDER}")
