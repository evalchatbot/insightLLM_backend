"""
API routes for the Chatbot agent (RAG, memory management).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from backend.agents.chatbot_agent import ChatbotAgent
from backend.utils.logging_config import get_logger

router = APIRouter(prefix="/chatbot", tags=["chatbot"])
logger = get_logger(__name__)

agent = ChatbotAgent()

class ChatbotAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: str
    conversation_id: Optional[str] = None

class ChatbotAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    context: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class ChatbotMultiAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: str
    book_ids: Optional[List[str]] = None
    max_iterations: Optional[int] = 3
    conversation_id: Optional[str] = None
    auto_create_conversation: Optional[bool] = False  # NEW: Auto-create conversation with title


class ChatbotMultiAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]  # resolved chunks (with book title/author if available)
    traces: List[Dict[str, Any]]  # per-iteration debug info


@router.post("/ask", response_model=ChatbotAskResponse)
async def ask_chatbot(req: ChatbotAskRequest) -> ChatbotAskResponse:
    """Ask a question to the chatbot agent (RAG, memory, vector search, async)."""
    try:
        logger.info(f"[API] Chatbot ask request: user={req.user_id[:8]}..., question_len={len(req.question)}, genre={req.genre}")
        
        if req.conversation_id:
            logger.info(f"[API] Using existing conversation: {req.conversation_id}")
        else:
            logger.info(f"[API] No conversation ID provided - messages will only be stored in memory")
        
        result = await agent.ask(
            user_id=req.user_id,
            session_id=req.session_id,
            question=req.question,
            genre=req.genre,
            conversation_id=req.conversation_id
        )
        
        # Add conversation_id to result if it was provided
        if req.conversation_id:
            result["metadata"]["conversation_id"] = req.conversation_id
        
        logger.info(f"[API] Chatbot response: answer_len={len(result.get('answer', ''))}, sources={len(result.get('sources', []))}")
        return ChatbotAskResponse(**result)
        
    except Exception as e:
        logger.error(f"[API] ❌ Chatbot ask failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/ask-multistep", response_model=ChatbotMultiAskResponse)
async def ask_chatbot_multistep(req: ChatbotMultiAskRequest) -> ChatbotMultiAskResponse:
    """
    Ask a question using the Multi-Step RAG pipeline (plan → retrieve → validate → synthesize).
    Does not affect the existing /chatbot/ask route.
    """
    try:
        result = await agent.ask_multi_step(
            user_id=req.user_id,
            session_id=req.session_id,
            question=req.question,
            genre=req.genre,
            book_ids=req.book_ids,
            max_iterations=req.max_iterations or 3,
            conversation_id=req.conversation_id
        )
        print("✅ Got result:", result)
        # result already matches the response model keys
        return ChatbotMultiAskResponse(**result)
    except Exception as e:
        print("❌ Error in ask_chatbot:", e)
        raise HTTPException(status_code=500, detail=str(e))