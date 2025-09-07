"""
Database models for users, books, chat_messages, document_chunks.
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime

class User(BaseModel):
    """User model."""
    id: str
    email: str
    name: Optional[str]
    created_at: Optional[datetime]

class Book(BaseModel):
    """Book metadata and file reference."""
    id: str
    title: str
    author: Optional[str]
    genre: str
    file_url: Optional[str]
    created_at: Optional[datetime]

class ChatMessage(BaseModel):
    """Stores conversation messages between users and assistant."""
    id: str
    user_id: str
    session_id: str
    sender: str  # 'user' or 'assistant'
    message: str
    timestamp: datetime

class DocumentChunk(BaseModel):
    """Book text split into chunks, with embeddings for vector search."""
    id: str
    book_id: str
    chunk_index: int
    text: str
    embedding: Optional[List[float]]
    genre: str
    created_at: Optional[datetime]


