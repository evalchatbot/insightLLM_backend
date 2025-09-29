# backend/rag/llm/groq_httpx.py
from __future__ import annotations
from typing import Optional
import httpx
import asyncio
from backend.rag.telemetry.langsmith_tracer import trace_llm_call

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

    @trace_llm_call(name="groq_generate", provider="groq")
    async def generate(self, prompt: str, *, temperature: float = 0.4, max_tokens: int = 2048) -> str:
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert CSS exam preparation assistant. Provide comprehensive, structured answers in **Markdown format**. Use ## for headings, **bold** for key terms, - for bullet points, and proper formatting for Introduction, Body (make relevant headings), and Conclusion sections."},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.url, headers=self.headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            response_content = (data["choices"][0]["message"]["content"] or "").strip()
            
            
            return response_content
