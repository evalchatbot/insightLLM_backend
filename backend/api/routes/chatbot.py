"""
API routes for the Chatbot agent (RAG, memory management).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from backend.agents.chatbot_agent import ChatbotAgent

router = APIRouter(prefix="/chatbot", tags=["chatbot"])

agent = ChatbotAgent()

class ChatbotAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: str

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


class ChatbotMultiAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]  # resolved chunks (with book title/author if available)
    traces: List[Dict[str, Any]]  # per-iteration debug info


@router.post("/ask", response_model=ChatbotAskResponse)
async def ask_chatbot(req: ChatbotAskRequest) -> ChatbotAskResponse:
    """Ask a question to the chatbot agent (RAG, memory, vector search, async)."""
    try:
        print("➡️ Incoming request:", req.dict())
        result = await agent.ask(
            user_id=req.user_id,
            session_id=req.session_id,
            question=req.question,
            genre=req.genre
        )
        return ChatbotAskResponse(**result)
    except Exception as e:
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
        )
        print("✅ Got result:", result)
        # result already matches the response model keys
        return ChatbotMultiAskResponse(**result)
    except Exception as e:
        print("❌ Error in ask_chatbot:", e)
        raise HTTPException(status_code=500, detail=str(e))