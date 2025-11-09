"""
Chatbot endpoints for the CSS/PMS-focused assistant.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agents.chatbot_agent import ChatbotAgent, SYSTEM_PROMPT_ID
from backend.utils.logging_config import get_logger

router = APIRouter(prefix="/chatbot", tags=["chatbot"])
logger = get_logger(__name__)

agent = ChatbotAgent()


class ChatbotAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: Optional[str] = "general"
    book_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None


class ChatbotAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    context: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class ChatbotStreamRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: Optional[str] = "general"
    book_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None


@router.post("/ask", response_model=ChatbotAskResponse)
async def ask_chatbot(req: ChatbotAskRequest) -> ChatbotAskResponse:
    """
    Handle a non-streaming chatbot request with memory updates.
    """
    try:
        logger.info(
            "[API] Chatbot ask: user=%s..., conversation=%s",
            req.user_id[:8],
            req.conversation_id or "memory",
        )
        result = await agent.ask(
            user_id=req.user_id,
            session_id=req.session_id,
            question=req.question,
            genre=req.genre or "general",
            book_ids=req.book_ids,
            conversation_id=req.conversation_id,
        )
        return ChatbotAskResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[API] Chatbot ask failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ask-multi", response_model=ChatbotAskResponse)
async def ask_chatbot_multi(req: ChatbotAskRequest) -> ChatbotAskResponse:
    """
    Backwards-compatible multi-step endpoint. Delegates to the simplified agent.
    """
    try:
        logger.info(
            "[API] Chatbot ask-multi: user=%s..., conversation=%s",
            req.user_id[:8],
            req.conversation_id or "memory",
        )
        result = await agent.ask_multi_step(
            user_id=req.user_id,
            session_id=req.session_id,
            question=req.question,
            genre=req.genre or "general",
            book_ids=req.book_ids,
            conversation_id=req.conversation_id,
        )
        return ChatbotAskResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[API] Chatbot ask-multi failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ask-stream")
async def ask_chatbot_stream(req: ChatbotStreamRequest) -> StreamingResponse:
    """
    Stream chatbot chunks as Server-Sent Events (SSE).
    """
    async def event_stream() -> AsyncGenerator[str, None]:
        start = time.time()
        try:
            stream = await agent.stream_answer(
                user_id=req.user_id,
                session_id=req.session_id,
                question=req.question,
                genre=req.genre or "general",
                book_ids=req.book_ids,
                conversation_id=req.conversation_id,
            )
            async for chunk in stream:
                payload = {"type": "chunk", "content": chunk}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            answer = stream.answer if hasattr(stream, "answer") else ""
            if not answer:
                answer = "".join(getattr(stream, "collected", []))
            answer = answer.strip()
            update_info = getattr(stream, "update_info", {}) or {}
            token_usage = getattr(stream, "token_usage", None) or {}
            metadata = {
                "mode": "single_llm_stream",
                "system_prompt": SYSTEM_PROMPT_ID,
                "response_time": round(time.time() - start, 3),
                "context_messages": getattr(stream, "context_messages", 0),
                "token_usage": token_usage,
            }
            metadata.update({k: v for k, v in (update_info or {}).items() if v is not None})
            analysis_meta = getattr(stream, "analysis", None)
            if analysis_meta:
                metadata["question_analysis"] = analysis_meta
            if "conversation_id" not in metadata:
                metadata["conversation_id"] = update_info.get("conversation_id") or req.conversation_id
            final_payload = {
                "type": "complete",
                "answer": answer,
                "sources": [],
                "citations": [],
                "metadata": metadata,
            }
            yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.error(f"[API] Streaming failed: {exc}")
            error_payload = {"type": "error", "error": str(exc)}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@router.get("/capabilities", response_model=Dict[str, Any])
async def get_capabilities() -> Dict[str, Any]:
    """
    Lightweight capabilities probe for health checks.
    """
    return await agent.get_agent_capabilities()
