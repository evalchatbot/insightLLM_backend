# backend/rag/llm/streaming_client.py
"""
Streaming LLM client for real-time response generation.
Provides true streaming capabilities for better user experience.
"""
from __future__ import annotations
from typing import AsyncGenerator, Optional, Tuple
import httpx
import json
import logging
from backend.rag.telemetry.langsmith_tracer import trace_llm_call
from backend.utils.usage_tracking import get_token_count

logger = logging.getLogger(__name__)

class StreamingLLMClient:
    """
    Streaming LLM client that supports real-time response generation.
    Uses Server-Sent Events (SSE) for streaming responses.
    """
    
    def __init__(self, api_key: str, model: str, provider: str = "groq"):
        if not api_key or not model:
            raise RuntimeError("StreamingLLMClient requires api_key and model.")
        self.api_key = api_key
        self.model = model
        self.provider = provider.lower()
        
        if self.provider == "groq":
            self.url = "https://api.groq.com/openai/v1/chat/completions"
        elif self.provider == "openai":
            self.url = "https://api.openai.com/v1/chat/completions"
        else:
            raise ValueError(f"Unsupported provider: {provider}")
            
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @trace_llm_call(name="streaming_generate", provider="streaming")
    async def generate_stream(
        self,
        prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 2048,
        system_message: Optional[str] = None
    ) -> AsyncGenerator[Tuple[str, Optional[dict]], None]:
        """
        Generate streaming response from LLM.
        
        Args:
            prompt: User prompt
            temperature: Response randomness (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            system_message: Optional system message override
            
        Yields:
            Tuple[str, Optional[dict]]: (content_chunk, token_usage_info)
            - content_chunk: Incremental response chunk (or None if only token info)
            - token_usage_info: Dict with 'prompt_tokens' and 'completion_tokens' (only in final chunk)
        """
        
        # Default system message with markdown formatting
        if system_message is None:
            system_message = (
                "You are an expert CSS exam preparation assistant. "
                "Always format your responses in **Markdown** with proper headings (##), "
                "**bold** text for key terms, bullet points (-), numbered lists, "
                "and structured formatting suitable for civil service examination preparation."
            )
        
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ]
        
        # Calculate input tokens using tiktoken
        full_prompt = system_message + "\n\n" + prompt
        input_tokens = get_token_count(full_prompt, model="gpt-4")
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": True  # Enable streaming
        }
        
        token_usage = None
        output_tokens = 0
        
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                logger.info(f"Starting streaming request to {self.provider}")
                
                async with client.stream(
                    "POST", 
                    self.url, 
                    headers=self.headers, 
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                            
                        # Remove 'data: ' prefix if present
                        if line.startswith("data: "):
                            line = line[6:]
                        
                        # Skip empty lines and [DONE] marker
                        if not line.strip() or line.strip() == "[DONE]":
                            continue
                            
                        try:
                            # Parse the JSON chunk
                            chunk_data = json.loads(line)
                            
                            # Check for token usage in the chunk (usually in final chunk)
                            if "usage" in chunk_data:
                                usage = chunk_data["usage"]
                                token_usage = {
                                    "prompt_tokens": usage.get("prompt_tokens", input_tokens),
                                    "completion_tokens": usage.get("completion_tokens", 0),
                                    "total_tokens": usage.get("total_tokens", 0)
                                }
                                # Yield token usage info with None content
                                yield (None, token_usage)
                                continue
                            
                            # Extract content from the chunk
                            if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                choice = chunk_data["choices"][0]
                                if "delta" in choice and "content" in choice["delta"]:
                                    content = choice["delta"]["content"]
                                    if content:  # Only yield non-empty content
                                        yield (content, None)
                                        
                        except json.JSONDecodeError:
                            # Skip invalid JSON lines
                            logger.warning(f"Failed to parse streaming chunk: {line}")
                            continue
                        except Exception as e:
                            logger.error(f"Error processing streaming chunk: {e}")
                            continue
                    
                    # If token usage wasn't provided by API, calculate it from collected content
                    if token_usage is None:
                        # Note: We can't calculate output tokens here since we're streaming
                        # The chatbot agent will calculate it from the full response
                        token_usage = {
                            "prompt_tokens": input_tokens,
                            "completion_tokens": 0,  # Will be calculated by agent
                            "total_tokens": input_tokens
                        }
                        yield (None, token_usage)
                            
        except Exception as e:
            logger.error(f"Streaming request failed: {e}")
            # Yield error message as fallback
            yield (f"[Streaming Error: {str(e)}]", None)

    async def generate_complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 2048,
        system_message: Optional[str] = None
    ) -> Tuple[str, dict]:
        """
        Generate complete response (non-streaming) for backward compatibility.
        
        Args:
            prompt: User prompt
            temperature: Response randomness
            max_tokens: Maximum tokens to generate
            system_message: Optional system message override
            
        Returns:
            Tuple[str, dict]: (complete_response, token_usage)
            - complete_response: Full response text
            - token_usage: Dict with 'prompt_tokens', 'completion_tokens', 'total_tokens'
        """
        chunks = []
        token_usage = None
        
        async for chunk, usage_info in self.generate_stream(
            prompt, 
            temperature=temperature, 
            max_tokens=max_tokens,
            system_message=system_message
        ):
            if chunk:
                chunks.append(chunk)
            if usage_info:
                token_usage = usage_info
        
        full_response = "".join(chunks)
        
        # If token usage wasn't provided, calculate it
        if token_usage is None or token_usage.get("completion_tokens", 0) == 0:
            full_prompt = (system_message or "") + "\n\n" + prompt
            prompt_tokens = get_token_count(full_prompt, model="gpt-4")
            completion_tokens = get_token_count(full_response, model="gpt-4")
            token_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
        
        return (full_response, token_usage)


def get_streaming_llm_client() -> StreamingLLMClient:
    """
    Get a streaming LLM client based on configuration.
    """
    from backend.rag.config import get_rag_settings
    
    settings = get_rag_settings()
    provider = (settings.LLM_PROVIDER or "groq").lower()
    
    if provider == "groq":
        if not settings.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY not set")
        return StreamingLLMClient(
            api_key=settings.GROQ_API_KEY,
            model=getattr(settings, "GROQ_MODEL_NAME", "llama-3.1-8b-instant"),
            provider="groq"
        )
    elif provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        return StreamingLLMClient(
            api_key=settings.OPENAI_API_KEY,
            model=getattr(settings, "OPENAI_MODEL_NAME", "gpt-4o-mini"),
            provider="openai"
        )
    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER for streaming: {provider}")
