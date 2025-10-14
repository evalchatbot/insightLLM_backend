"""
Assistant Router
Routes incoming queries via IntentAgent to either the RAG ChatbotAgent (book-specific)
or the ConversationalAgent (general chit-chat).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import asyncio

from backend.utils.logging_config import get_logger
from backend.agents.intent_agent import IntentAgent
from backend.agents.chatbot_agent import ChatbotAgent
from backend.agents.conversational_agent import ConversationalAgent


router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = get_logger(__name__)

intent_agent = IntentAgent()
chatbot_agent = ChatbotAgent()
convo_agent = ConversationalAgent()


class AssistantAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: str
    book_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None


class AssistantAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    context: List[Dict[str, Any]]
    metadata: Dict[str, Any]


@router.post("/ask", response_model=AssistantAskResponse)
async def assistant_ask(req: AssistantAskRequest) -> AssistantAskResponse:
    try:
        # sanitize suspicious questions that embed previous context
        def _sanitize_question(raw: str) -> str:
            try:
                if not raw:
                    return raw
                txt = raw
                if ("Please provide a comprehensive" in txt) or ("Previous context:" in txt) or ("Current question:" in txt):
                    if "Current question:" in txt:
                        parts = txt.split("Current question:")
                        if len(parts) > 1:
                            cand = parts[-1].strip().strip('\n\r .,!?')
                            if len(cand) > 5:
                                return cand
                    lines = [l.strip() for l in txt.splitlines()]
                    for line in lines:
                        if not line or line.endswith(":"):
                            continue
                        if line.startswith(("User:", "Assistant:")):
                            continue
                        if len(line) > 10 and ("?" in line or any(w in line.lower() for w in ["discuss", "explain", "analyze", "what", "how", "why"])):
                            return line
                    for line in lines:
                        if len(line) > 20 and not line.startswith(("Please", "Previous", "Current", "User:", "Assistant:")):
                            return line
                return raw
            except Exception:
                return raw

        cleaned_q = _sanitize_question(req.question)
        if cleaned_q != req.question:
            logger.warning("[ASSISTANT] Sanitized incoming question to remove embedded context")

        # 1) Classify intent (LLM-based with heuristic fallback)
        intent = await intent_agent.classify_async(cleaned_q, genre=req.genre, book_ids=req.book_ids)
        intent_label = intent.get("intent", "book_specific")
        logger.info(f"[ASSISTANT] Intent: {intent_label}, conf={intent.get('confidence'):.2f}, reason={intent.get('reason')}")

        # 2) Route to appropriate agent
        if intent_label == "general":
            result = await convo_agent.ask(
                user_id=req.user_id,
                session_id=req.session_id,
                question=cleaned_q,
                genre=req.genre,
                conversation_id=req.conversation_id,
            )
        else:
            result = await chatbot_agent.ask(
                user_id=req.user_id,
                session_id=req.session_id,
                question=cleaned_q,
                genre=req.genre,
                book_ids=req.book_ids,
                conversation_id=req.conversation_id,
            )

        # 3) Annotate routing metadata
        result.setdefault("metadata", {})
        result["metadata"].update({
            "router_intent": intent_label,
            "router_confidence": intent.get("confidence"),
            "router_reason": intent.get("reason"),
            "routed_to": "conversational" if intent_label == "general" else "chatbot",
        })

        return AssistantAskResponse(**result)
    except Exception as e:
        logger.error(f"[ASSISTANT] ask failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
