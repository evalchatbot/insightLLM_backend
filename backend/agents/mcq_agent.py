"""
MCQ Agent module.
Handles MCQ generation, evaluation, and persistent storage in Supabase.
"""
from typing import List, Dict, Any
from datetime import datetime
from backend.db.supabase_client import SupabaseDB
from backend.config import GROQ_API_KEY, MCQ_LLM_MODEL
from backend.rag.telemetry.langsmith_tracer import trace_agent_method, trace_llm_call
import httpx

class MCQAgent:
    """
    MCQ agent for quiz generation, evaluation, and persistent storage.
    """
    def __init__(self):
        self.db = SupabaseDB()
        self.llm_model = MCQ_LLM_MODEL
        self.groq_api_key = GROQ_API_KEY

    @trace_agent_method(name="mcq_generate", tags=["mcq", "generation"])
    def generate_mcq(self, user_id: str, genre: str, context: str = "") -> Dict[str, Any]:
        """
        Generate MCQs from genre or chat context, store in Supabase.
        Returns quiz_id and questions.
        """
        # Compose prompt for MCQ generation
        prompt = self._compose_mcq_prompt(genre, context)
        questions = self._call_llm_groq(prompt)
        # For now, fallback to stub if LLM fails
        if not isinstance(questions, list):
            questions = [
                {
                    "question": f"Sample question {i+1} for genre {genre}",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": "A"
                } for i in range(3)
            ]
        quiz_id = f"quiz_{datetime.utcnow().timestamp()}_{user_id}"
        self.db.insert("mcq_quizzes", {"id": quiz_id, "user_id": user_id, "genre": genre, "created_at": datetime.utcnow().isoformat()})
        for q in questions:
            self.db.insert("mcq_questions", {"id": f"q_{quiz_id}_{q['question'][:10]}", "quiz_id": quiz_id, **q})
        return {"quiz_id": quiz_id, "questions": questions}

    def _compose_mcq_prompt(self, genre: str, context: str) -> str:
        """Compose prompt for MCQ LLM generation."""
        base = f"Generate 3 multiple-choice questions for the genre '{genre}'. Each question should have 4 options and specify the correct answer."
        if context:
            base += f"\nContext: {context}"
        base += "\nReturn as a JSON list of objects with fields: question, options, correct_answer."
        return base

    @trace_llm_call(name="mcq_groq_call", provider="groq")
    def _call_llm_groq(self, prompt: str) -> List[Dict[str, Any]]:
        """Call the GROQ API to get MCQs from the configured LLM model."""
        if not self.groq_api_key or not self.llm_model:
            return []
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": "You are an MCQ generator for books."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 512,
            "temperature": 0.7
        }
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                # Try to parse as JSON list
                import json
                return json.loads(content)
        except Exception as e:
            return []

    @trace_agent_method(name="mcq_evaluate", tags=["mcq", "evaluation"])
    def evaluate_mcq(self, user_id: str, quiz_id: str, answers: List[str]) -> Dict[str, Any]:
        """
        Evaluate user answers, store results, and return score/feedback.
        """
        # Retrieve correct answers
        res = self.db.select("mcq_questions", {"quiz_id": quiz_id})
        questions = res.data if hasattr(res, 'data') else []
        correct = [q["correct_answer"] for q in questions]
        score = sum([1 for a, c in zip(answers, correct) if a == c])
        feedback = f"You scored {score} out of {len(correct)}."
        result_id = f"result_{datetime.utcnow().timestamp()}_{user_id}"
        self.db.insert("mcq_results", {
            "id": result_id,
            "quiz_id": quiz_id,
            "user_id": user_id,
            "answers": answers,
            "score": score,
            "feedback": feedback,
            "attempted_at": datetime.utcnow().isoformat()
        })
        return {"score": score, "feedback": feedback}
