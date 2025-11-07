#!/usr/bin/env python3
"""
Lightweight Grok API client used for the new evaluation pipeline.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


class GrokError(RuntimeError):
    """Raised when the Grok API returns an error payload."""


@dataclass
class GrokMessage:
    role: str
    content: Any

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "content": self.content}


class GrokClient:
    """
    Very small convenience wrapper around the Grok chat completion endpoint.
    """

    def __init__(self, api_key: Optional[str] = None, *, timeout: int = 150) -> None:
        key = api_key or os.getenv("GROK_API") or os.getenv("Grok_API")
        if not key:
            raise RuntimeError(
                "Missing Grok API key. Set GROK_API or Grok_API in the environment."
            )
        self.api_key = key
        self.timeout = timeout
        self.base_url = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

    def chat_completion(
        self,
        *,
        model: str,
        messages: List[GrokMessage],
        response_format: Optional[Dict[str, Any]] = None,
        temperature: float = 0.1,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload),
            timeout=self.timeout,
        )

        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise GrokError(f"Grok API error {response.status_code}: {detail}")

        try:
            data = response.json()
        except ValueError as exc:
            raise GrokError(f"Invalid JSON in Grok response: {exc}") from exc

        return data


def extract_content_text(payload: Dict[str, Any]) -> str:
    """
    Helper to safely pull the first choice message content from a completion payload.
    """

    try:
        choices = payload["choices"]
        if not choices:
            raise KeyError("choices empty")
        message = choices[0]["message"]
        return message.get("content") or ""
    except Exception as exc:  # noqa: BLE001
        raise GrokError(f"Malformed Grok response: {payload}") from exc
