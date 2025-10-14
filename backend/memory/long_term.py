"""
Long-term memory management using Supabase.
Persists conversation summaries, important facts, and user preferences.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from backend.db.supabase_client import SupabaseDB
from backend.db.supabase_service import SupabaseService
import os
import uuid
from backend.memory.conversation_summarizer import get_conversation_summarizer

logger = logging.getLogger(__name__)

class LongTermMemory:
    """
    Manages long-term memory by persisting key facts and context in Supabase.
    Organizes memory by user/session/context.
    """
    def __init__(self):
        self.db = SupabaseDB()
        self.table = "long_term_memory"  # Table must exist in Supabase
        self.summarizer = get_conversation_summarizer()
        # Optional DB service for user id normalization
        try:
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            self.db_service = SupabaseService(supabase_url, supabase_key) if supabase_url and supabase_key else None
        except Exception:
            self.db_service = None

    def _normalize_user_id(self, user_id: str) -> Optional[str]:
        """Ensure user_id is a valid UUID for the DB schema. If not, try to fallback.
        Order of resolution:
        1) If input is already a valid UUID, use it.
        2) If service is available, try DB fallback (an existing user UUID).
        3) Otherwise, generate a fresh UUID (per schema, no FK required).
        """
        try:
            _ = uuid.UUID(str(user_id))
            return str(user_id)
        except Exception:
            # Generate a new UUID whenever the provided user_id is not a UUID.
            # This avoids attributing memory to another existing user.
            new_id = str(uuid.uuid4())
            logger.warning(
                f"[LTM] Non-UUID user_id '{user_id}' provided; generating new UUID {new_id} for long-term memory"
            )
            return new_id

    def save_fact(self, user_id: str, session_id: str, context: str, fact: str) -> Any:
        """
        Persist a fact or context snippet to Supabase.
        This method is kept for backward compatibility but should use save_summary for conversations.
        """
        norm_user = self._normalize_user_id(user_id)
        if not norm_user:
            # Skip DB write if we cannot ensure UUID
            return None

        data = {
            "user_id": norm_user,
            "session_id": session_id,
            "context": context,
            "fact": fact,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        return self.db.insert(self.table, data)
    
    async def save_conversation_summary(
        self, 
        user_id: str, 
        session_id: str, 
        messages: List[Dict[str, Any]],
        context: str = "chat"
    ) -> Any:
        """
        Save a conversation summary instead of individual messages.
        This is the preferred method for storing conversation context.
        """
        try:
            # Create rich summary with context
            summary_data = await self.summarizer.create_contextual_summary(messages)
            
            norm_user = self._normalize_user_id(user_id)
            if not norm_user:
                return None

            data = {
                "user_id": norm_user,
                "session_id": session_id,
                "context": context,
                "fact": summary_data["summary"],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
            
            logger.info(f"Saving conversation summary for {user_id}/{session_id}: {len(messages)} messages → {len(summary_data['summary'])} chars")
            return self.db.insert(self.table, data)
            
        except Exception as e:
            logger.error(f"Failed to save conversation summary: {e}")
            # Fallback to saving the last message as a fact
            if messages:
                last_message = messages[-1].get("message", "")
                return self.save_fact(user_id, session_id, context, last_message)
            return None
    
    async def save_smart_context(
        self, 
        user_id: str, 
        session_id: str, 
        current_messages: List[Dict[str, Any]], 
        new_fact: str,
        context: str = "chat"
    ) -> Any:
        """
        Intelligently save context - either as summary or individual fact.
        This is the main method agents should use.
        """
        # If we have enough messages, summarize them
        if len(current_messages) >= self.summarizer.context_threshold:
            return await self.save_conversation_summary(user_id, session_id, current_messages, context)
        else:
            # For short conversations, save the fact directly
            return self.save_fact(user_id, session_id, context, new_fact)

    def get_facts(self, user_id: str, session_id: Optional[str] = None, context: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve facts for a user, optionally filtered by session/context."""
        filters = {"user_id": user_id}
        if session_id:
            filters["session_id"] = session_id
        if context:
            filters["context"] = context
        res = self.db.select(self.table, filters)
        return res.data if hasattr(res, 'data') else []
    
    def get_conversation_summaries(self, user_id: str, session_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve conversation summaries for a user."""
        try:
            query = (
                self.db.supabase.table(self.table)
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if session_id:
                query = query.eq("session_id", session_id)
            res = query.execute()
            return res.data if hasattr(res, 'data') else []
        except Exception as e:
            logger.error(f"Failed to retrieve conversation summaries: {e}")
            return []
    
    def get_user_context(self, user_id: str, max_summaries: int = 5) -> str:
        """
        Get condensed user context from recent conversation summaries.
        This replaces the need to load all individual messages.
        """
        summaries = self.get_conversation_summaries(user_id, limit=max_summaries)
        
        if not summaries:
            return "No previous conversation context available."
        
        context_parts = []
        for summary in summaries:
            fact = summary.get("fact", "")
            session_id = summary.get("session_id", "")
            created_at = summary.get("created_at", "")
            
            # Extract just the summary text (remove metadata)
            summary_text = fact.split("\n\n[Metadata:")[0] if "[Metadata:" in fact else fact
            context_parts.append(f"Session {session_id}: {summary_text}")
        
        return "\n\n".join(context_parts)
    
    async def cleanup_old_facts(self, user_id: str, session_id: str) -> None:
        """
        Clean up old individual facts when a summary is created.
        Removes redundant storage after summarization.
        """
        try:
            # With the simplified schema, we skip archival and keep summaries compact.
            # Optionally, we could delete older rows, but avoiding destructive ops by default.
            logger.info(f"[LTM] cleanup_old_facts noop for {user_id}/{session_id} (schema without content_type)")
        except Exception as e:
            logger.error(f"Failed to cleanup old facts: {e}")
