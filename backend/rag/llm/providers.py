# backend/rag/llm/providers.py
from __future__ import annotations
import asyncio
from typing import Any
from backend.rag.config import get_rag_settings

class BaseLLM:
    async def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 900) -> str:
        raise NotImplementedError

class OpenAILLM(BaseLLM):
    def __init__(self, api_key: str | None, model_name: str = "gpt-4o-mini"):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError("openai package not installed. `pip install openai`") from e
        self._OpenAI = OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name

    async def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 900) -> str:
        # Use chat.completions for broad compatibility
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model_name,  # configurable
                messages=[
                    {"role": "system", "content": "You are an expert CSS exam preparation assistant. Always format your responses in **Markdown** with proper headings (##), **bold** text for key terms, bullet points (-), and structured formatting."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        return await asyncio.to_thread(_call)

class GroqLLM(BaseLLM):
    def __init__(self, api_key: str | None, model_name: str = "llama-3.1-8b-instant"):
        try:
            from groq import Groq  # type: ignore
        except Exception as e:
            raise RuntimeError("groq package not installed. `pip install groq`") from e
        self.client = Groq(api_key=api_key)
        self.model_name = model_name

    async def generate(self, prompt: str, *, temperature: float = 0.2, max_tokens: int = 900) -> str:
        def _call():
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are an expert CSS exam preparation assistant. Always format your responses in **Markdown** with proper headings (##), **bold** text for key terms, bullet points (-), and structured formatting."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        return await asyncio.to_thread(_call)

def get_llm() -> BaseLLM:
    s = get_rag_settings()
    provider = (s.LLM_PROVIDER or "groq").lower()
    if provider == "openai":
        # Allow model override via env if present; default to gpt-4o-mini
        model_name = getattr(s, "OPENAI_MODEL_NAME", "gpt-4o-mini")
        # OpenAI SDK can also read from .env; we allow None here
        return OpenAILLM(api_key=s.OPENAI_API_KEY, model_name=model_name)
    elif provider == "groq":
        if not s.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY not set")
        # Default to a currently supported model
        model_name = getattr(s, "GROQ_MODEL_NAME", "llama-3.1-8b-instant")
        return GroqLLM(api_key=s.GROQ_API_KEY, model_name=model_name)
    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {s.LLM_PROVIDER}")
