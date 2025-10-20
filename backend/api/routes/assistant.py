"""
Unified assistant router that proxies directly to the exam-focused ChatbotAgent.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from backend.agents.chatbot_agent import ChatbotAgent
from backend.utils.logging_config import get_logger

router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = get_logger(__name__)

chatbot_agent = ChatbotAgent()


class AssistantAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: Optional[str] = "general"
    book_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None


class AssistantAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    context: List[Dict[str, Any]]
    metadata: Dict[str, Any]


@router.post("/ask", response_model=AssistantAskResponse)
async def assistant_ask(req: AssistantAskRequest) -> AssistantAskResponse:
    """
    Delegate to the CSS/PMS tutor chatbot and annotate metadata for clients that
    still call the legacy assistant endpoint.
    """
    try:
        result = await chatbot_agent.ask(
            user_id=req.user_id,
            session_id=req.session_id,
            question=req.question,
            genre=req.genre or "general",
            book_ids=req.book_ids,
            conversation_id=req.conversation_id,
        )
        result.setdefault("metadata", {})
        result["metadata"].update(
            {
                "router": "single_llm",
                "router_intent": "exam_tutor",
                "routed_to": "chatbot",
            }
        )
        return AssistantAskResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[ASSISTANT] ask failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
