"""
API routes for conversation management (ChatGPT-style conversations).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import logging
import os

from backend.db.models import (
    ConversationCreateRequest, 
    ConversationListResponse, 
    ConversationMessagesResponse,
    Conversation,
    ConversationMessage
)
from backend.db.supabase_service import SupabaseService
from backend.agents.chatbot_agent import ChatbotAgent
from backend.utils.logging_config import get_logger

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Initialize services
supabase_service = SupabaseService(
    supabase_url=os.getenv("SUPABASE_URL"),
    supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

# Initialize chatbot agent for title generation
chatbot_agent = ChatbotAgent()

logger = get_logger(__name__)


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    book_ids: Optional[List[str]] = None


class ConversationWithQuestionRequest(BaseModel):
    """Request to create conversation with auto-generated title from first question/answer."""
    user_id: str
    question: str
    answer: str
    genre: Optional[str] = "General"
    book_ids: Optional[List[str]] = None


class NewChatRequest(BaseModel):
    """Request to create a new empty chat conversation."""
    user_id: str
    title: Optional[str] = "New Chat"
    genre: Optional[str] = "General"
    book_ids: Optional[List[str]] = None


class ConversationMessageRequest(BaseModel):
    """Request to add a message to a conversation."""
    sender: str  # 'user' or 'assistant'
    message: str
    citations: Optional[List[dict]] = Field(default_factory=list)
    metadata: Optional[dict] = Field(default_factory=dict)


@router.post("/new-chat", response_model=Conversation)
async def create_new_chat(req: NewChatRequest) -> Conversation:
    """Create a new empty chat conversation (for 'New Chat' button)."""
    try:
        logger.info(f"[API] Creating new chat for user: {req.user_id[:8]}...")
        
        # Validate and get proper user_id
        valid_user_id = supabase_service.get_valid_user_id(req.user_id)
        if not valid_user_id:
            logger.error(f"[API] No valid user found for: {req.user_id}")
            raise HTTPException(status_code=400, detail="No valid user found for conversation creation")
        
        conversation_data = {
            "user_id": valid_user_id,
            "title": req.title or "New Chat",
            "genre": req.genre or "General",
            "book_ids": req.book_ids or []
        }
        
        logger.info(f"[API] Creating conversation with title: {conversation_data['title']}")
        result = supabase_service.create_conversation(conversation_data)
        if not result:
            logger.error(f"[API] Failed to create conversation for user: {valid_user_id}")
            raise HTTPException(status_code=500, detail="Failed to create conversation")
        
        logger.info(f"[API] ✅ New chat created: {result['id']}")
        return Conversation(**result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Error creating new chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=Conversation)
async def create_conversation(req: ConversationCreateRequest) -> Conversation:
    """Create a new conversation."""
    try:
        # Validate and get proper user_id
        valid_user_id = supabase_service.get_valid_user_id(req.user_id)
        if not valid_user_id:
            raise HTTPException(status_code=400, detail="No valid user found for conversation creation")
        
        conversation_data = {
            "user_id": valid_user_id,  # Use validated user_id
            "title": req.title,
            "genre": req.genre,
            "book_ids": req.book_ids
        }
        
        result = supabase_service.create_conversation(conversation_data)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to create conversation")
        
        return Conversation(**result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auto-title", response_model=Conversation)
async def create_conversation_with_auto_title(req: ConversationWithQuestionRequest) -> Conversation:
    """Create a new conversation with auto-generated title from question and answer."""
    try:
        # Validate and get proper user_id
        valid_user_id = supabase_service.get_valid_user_id(req.user_id)
        if not valid_user_id:
            raise HTTPException(status_code=400, detail="No valid user found for conversation creation")
        
        # Create conversation with auto-generated title
        conversation_id = await chatbot_agent.create_conversation_with_title(
            user_id=valid_user_id,
            first_question=req.question,
            first_answer=req.answer,
            genre=req.genre or "General",
            book_ids=req.book_ids
        )
        
        if not conversation_id:
            raise HTTPException(status_code=500, detail="Failed to create conversation with title")
        
        # Get the created conversation to return
        conversation_data = supabase_service.get_conversation_by_id(conversation_id, valid_user_id)
        if not conversation_data:
            raise HTTPException(status_code=500, detail="Conversation created but could not retrieve")
        
        return Conversation(**conversation_data)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating conversation with auto-title: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=ConversationListResponse)
async def get_user_conversations(
    user_id: str,
    limit: int = Query(50, ge=1, le=100)
) -> ConversationListResponse:
    """Get all conversations for a user (for conversation list in frontend)."""
    try:
        logger.info(f"[API] Getting conversations for user: {user_id[:8]}..., limit: {limit}")
        
        conversations_data = supabase_service.get_user_conversations(user_id, limit)
        conversations = [Conversation(**conv) for conv in conversations_data]
        
        logger.info(f"[API] ✅ Found {len(conversations)} conversations for user")
        
        return ConversationListResponse(
            conversations=conversations,
            total=len(conversations)
        )
    
    except Exception as e:
        logger.error(f"[API] Error getting user conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{conversation_id}", response_model=ConversationMessagesResponse)
async def get_conversation_with_messages(
    conversation_id: str,
    user_id: Optional[str] = None
) -> ConversationMessagesResponse:
    """Get a conversation with all its messages."""
    try:
        # Get conversation
        conversation_data = supabase_service.get_conversation_by_id(conversation_id, user_id)
        if not conversation_data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Get all messages (no limit)
        messages_data = supabase_service.get_conversation_messages(conversation_id, limit=10000, offset=0)
        
        conversation = Conversation(**conversation_data)
        messages = [ConversationMessage(**msg) for msg in messages_data]
        
        return ConversationMessagesResponse(
            conversation=conversation,
            messages=messages
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation with messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{conversation_id}/messages", response_model=List[ConversationMessage])
async def get_conversation_messages(
    conversation_id: str,
    user_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0)
) -> List[ConversationMessage]:
    """Get messages for a specific conversation."""
    try:
        # Verify conversation exists and user has access
        conversation_data = supabase_service.get_conversation_by_id(conversation_id, user_id)
        if not conversation_data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        messages_data = supabase_service.get_conversation_messages(conversation_id, limit, offset)
        return [ConversationMessage(**msg) for msg in messages_data]
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{conversation_id}/messages", response_model=ConversationMessage)
async def add_conversation_message(
    conversation_id: str,
    req: ConversationMessageRequest,
    user_id: Optional[str] = None
) -> ConversationMessage:
    """Add a message to a conversation."""
    try:
        logger.info(f"[API] Adding message to conversation: {conversation_id}")
        
        # Verify conversation exists and user has access
        conversation_data = supabase_service.get_conversation_by_id(conversation_id, user_id)
        if not conversation_data:
            logger.error(f"[API] Conversation not found: {conversation_id}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Validate sender field
        if req.sender not in ["user", "assistant"]:
            raise HTTPException(status_code=400, detail="Sender must be 'user' or 'assistant'")
        
        # Prepare message data
        message_data = {
            "conversation_id": conversation_id,
            "sender": req.sender,
            "message": req.message,
            "citations": req.citations or [],
            "metadata": req.metadata or {}
        }
        
        logger.info(f"[API] Adding {req.sender} message: {len(req.message)} chars")
        
        # Add message to database
        result = supabase_service.add_conversation_message(message_data)
        if not result:
            logger.error(f"[API] Failed to add message to conversation: {conversation_id}")
            raise HTTPException(status_code=500, detail="Failed to add message")
        
        logger.info(f"[API] ✅ Message added successfully: {result['id']}")
        return ConversationMessage(**result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Error adding conversation message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{conversation_id}", response_model=Conversation)
async def update_conversation(
    conversation_id: str,
    req: ConversationUpdateRequest,
    user_id: Optional[str] = None
) -> Conversation:
    """Update conversation metadata."""
    try:
        # Verify conversation exists and user has access
        conversation_data = supabase_service.get_conversation_by_id(conversation_id, user_id)
        if not conversation_data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Prepare updates
        updates = {}
        if req.title is not None:
            updates["title"] = req.title
        if req.genre is not None:
            updates["genre"] = req.genre
        if req.book_ids is not None:
            updates["book_ids"] = req.book_ids
        
        if not updates:
            # Return existing conversation if no updates
            return Conversation(**conversation_data)
        
        # Apply updates
        success = supabase_service.update_conversation(conversation_id, updates)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update conversation")
        
        # Get updated conversation
        updated_data = supabase_service.get_conversation_by_id(conversation_id, user_id)
        return Conversation(**updated_data)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user_id: Optional[str] = None
) -> Dict[str, str]:
    """Delete (deactivate) a conversation."""
    try:
        success = supabase_service.delete_conversation(conversation_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found or already deleted")
        
        return {"message": "Conversation deleted successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper endpoint for debugging
@router.get("/{conversation_id}/info", response_model=Dict[str, Any])
async def get_conversation_info(
    conversation_id: str,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get conversation information including message count."""
    try:
        conversation_data = supabase_service.get_conversation_by_id(conversation_id, user_id)
        if not conversation_data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        messages_data = supabase_service.get_conversation_messages(conversation_id, limit=1000)
        
        return {
            "conversation": conversation_data,
            "actual_message_count": len(messages_data),
            "stored_message_count": conversation_data.get("message_count", 0),
            "last_updated": conversation_data.get("updated_at"),
            "is_active": conversation_data.get("is_active", True)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation info: {e}")
        raise HTTPException(status_code=500, detail=str(e))
