"""
Conversational Agent
Handles general conversation without RAG. Uses LLM directly, with optional memory and DB persistence.
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
import time

from backend.memory.short_term import ShortTermMemory
from backend.memory.long_term import LongTermMemory
from backend.utils.logging_config import get_logger
from backend.db.supabase_service import SupabaseService
from backend.rag.llm.providers import get_llm
from backend.rag.config import get_rag_settings
import os


class ConversationalAgent:
    def __init__(self):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()
        self.logger = get_logger(__name__)
        self.llm = get_llm()
        try:
            s = get_rag_settings()
            model_name = getattr(self.llm, "model_name", None)
            self.logger.info(
                f"[CONVERSATION] LLM provider={s.LLM_PROVIDER} model={model_name or 'default'}"
            )
        except Exception:
            pass

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if supabase_url and supabase_key:
            try:
                self.db_service = SupabaseService(supabase_url, supabase_key)
            except Exception as e:
                self.logger.error(f"[CONVERSATION] DB init failed: {e}")
                self.db_service = None
        else:
            self.db_service = None

    async def ask(
        self,
        user_id: str,
        session_id: str,
        question: str,
        genre: str,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        start = time.time()
        try:
            # Emergency sanitize if question carries embedded previous context
            if ("Please provide a comprehensive" in question) or ("Previous context:" in question) or ("Current question:" in question):
                clean_q = self._extract_clean_question_emergency(question)
                if clean_q != question:
                    self.logger.warning("[CONVERSATION] Sanitized incoming question to remove embedded context")
                    question = clean_q
            # Build context
            if conversation_id and self.db_service:
                context = await self._get_conversation_context(conversation_id)
            else:
                context = self.short_term.get_recent_messages(user_id, session_id)

            # Compose a simple chat prompt with context
            history_text = "\n".join(
                f"{m.get('sender','user').title()}: {m.get('message','')}" for m in context[-8:]
            )
            prompt = (
                "You are a friendly, helpful conversational assistant. Keep answers concise, clear, and helpful.\n\n"
                + (f"Conversation so far:\n{history_text}\n\n" if history_text else "")
                + f"User: {question}\nAssistant:"
            )

            answer = await self.llm.generate(prompt, temperature=0.6, max_tokens=500)

            # Memory updates
            await self._update_conversation_memory(
                user_id, session_id, question, answer, conversation_id
            )

            return {
                "answer": answer or "",
                "sources": [],
                "citations": [],
                "context": context,
                "metadata": {
                    "routed_to": "conversational",
                    "question_type": "generic",
                    "mode": "llm",
                    "total_execution_time": time.time() - start,
                },
            }
        except Exception as e:
            self.logger.error(f"[CONVERSATION] ask failed: {e}")
            return {
                "answer": "Sorry, I hit a snag handling that message.",
                "sources": [],
                "citations": [],
                "context": [],
                "metadata": {"error": str(e), "routed_to": "conversational"},
            }

    def _extract_clean_question_emergency(self, contaminated_question: str) -> str:
        try:
            if "Current question:" in contaminated_question:
                parts = contaminated_question.split("Current question:")
                if len(parts) > 1:
                    clean = parts[-1].strip().strip('\n\r .,!?')
                    if len(clean) > 5:
                        return clean
            lines = contaminated_question.split('\n')
            for line in lines:
                t = line.strip()
                if not t or t.endswith(":") or t.startswith(("User:", "Assistant:", "Please", "Previous", "Current")):
                    continue
                if len(t) > 10 and ("?" in t or any(w in t.lower() for w in ["discuss", "explain", "analyze", "what", "how", "why"])):
                    return t
            for line in lines:
                t = line.strip()
                if len(t) > 20 and not t.startswith(("User:", "Assistant:", "Please", "Previous", "Current")):
                    return t
            return contaminated_question
        except Exception:
            return contaminated_question

    async def _update_conversation_memory(
        self,
        user_id: str,
        session_id: str,
        question: str,
        answer: str,
        conversation_id: Optional[str] = None,
    ) -> None:
        try:
            if conversation_id and self.db_service:
                await self._save_to_conversation_db(conversation_id, question, answer)

            self.short_term.add_message(user_id, session_id, {"sender": "user", "message": question})
            self.short_term.add_message(user_id, session_id, {"sender": "assistant", "message": answer})

            if self.short_term.should_summarize(user_id, session_id):
                msgs = self.short_term.get_recent_messages(user_id, session_id)
                await self.long_term.save_conversation_summary(user_id, session_id, msgs)
                self.short_term.reset_conversation_count(user_id, session_id)
                await self.long_term.cleanup_old_facts(user_id, session_id)
            else:
                self.long_term.save_fact(user_id, session_id, context="chat", fact=answer)
        except Exception as e:
            self.logger.warning(f"[CONVERSATION] memory update failed: {e}")

    async def _get_conversation_context(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        try:
            if not self.db_service:
                return []
            messages = self.db_service.get_recent_conversation_messages(conversation_id, limit)
            context = []
            for msg in messages:
                if msg.get("user_prompt"):
                    context.append({
                        "sender": "user",
                        "message": msg.get("user_prompt", ""),
                        "timestamp": msg.get("created_at"),
                    })
                if msg.get("llm_response"):
                    context.append({
                        "sender": "assistant",
                        "message": msg.get("llm_response", ""),
                        "timestamp": msg.get("created_at"),
                    })
            return context
        except Exception:
            return []

    async def _save_to_conversation_db(self, conversation_id: str, question: str, answer: str) -> None:
        try:
            if not self.db_service:
                return
            self.db_service.add_message_pair(conversation_id, question, answer)
        except Exception:
            pass
