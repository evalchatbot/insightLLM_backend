"""
Database models aligned with updated schema.
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class User(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Book(BaseModel):
    id: str
    title: str
    author: str
    genre: str
    total_pages: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DocumentChunk(BaseModel):
    id: str
    book_id: str
    content: str
    page_start: int
    page_end: int
    chunk_index: int
    embedding: Optional[List[float]] = None
    metadata: Optional[dict] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class Conversation(BaseModel):
    id: str
    user_id: str
    chat_id: str
    title: Optional[str] = None
    icon: Optional[str] = None
    is_pinned: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConversationMessage(BaseModel):
    id: str
    conversation_id: str
    user_prompt: Optional[str] = None
    llm_response: Optional[str] = None
    img_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConversationCreateRequest(BaseModel):
    user_id: str
    title: Optional[str] = None
    icon: Optional[str] = None
    is_pinned: Optional[bool] = False


class ConversationListResponse(BaseModel):
    conversations: List[Conversation]
    total: int


class ConversationMessagesResponse(BaseModel):
    conversation: Conversation
    messages: List[ConversationMessage]
