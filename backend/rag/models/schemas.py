from __future__ import annotations
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    thread_id: Optional[str] = None
    messages: List[Dict] = Field(default_factory=list, description="List of {role, content}")
    selection: Optional[Dict] = None
    max_iterations: Optional[int] = None
    stream: bool = False

class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    source: str
    start_char: int
    end_char: int

class StepTrace(BaseModel):
    iteration: int
    subquestions: List[str] = Field(default_factory=list)
    retrieved_ids: List[str] = Field(default_factory=list)
    notes: str = ""

class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    iterations: int = 0
    traces: List[StepTrace] = Field(default_factory=list)
    budget_used: Dict = Field(default_factory=dict)
