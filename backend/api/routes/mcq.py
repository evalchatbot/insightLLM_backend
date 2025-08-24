"""
API routes for the MCQ agent (generation, evaluation, history).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from backend.agents.mcq_agent import MCQAgent

router = APIRouter(prefix="/mcq", tags=["mcq"])

agent = MCQAgent()

class MCQGenerateRequest(BaseModel):
    user_id: str
    genre: str
    context: str = ""

class MCQGenerateResponse(BaseModel):
    quiz_id: str
    questions: List[Dict[str, Any]]

class MCQEvaluateRequest(BaseModel):
    user_id: str
    quiz_id: str
    answers: List[str]

class MCQEvaluateResponse(BaseModel):
    score: int
    feedback: str

@router.post("/generate", response_model=MCQGenerateResponse)
def generate_mcq(req: MCQGenerateRequest) -> MCQGenerateResponse:
    """Generate MCQs from genre or chat context."""
    try:
        result = agent.generate_mcq(user_id=req.user_id, genre=req.genre, context=req.context)
        return MCQGenerateResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluate", response_model=MCQEvaluateResponse)
def evaluate_mcq(req: MCQEvaluateRequest) -> MCQEvaluateResponse:
    """Evaluate user's MCQ answers and return score/feedback."""
    try:
        result = agent.evaluate_mcq(user_id=req.user_id, quiz_id=req.quiz_id, answers=req.answers)
        return MCQEvaluateResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
