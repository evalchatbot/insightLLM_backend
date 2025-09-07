"""
Long-term memory management using Supabase.
Persists conversation summaries, important facts, and user preferences.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from backend.db.supabase_client import SupabaseDB
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

    def save_fact(self, user_id: str, session_id: str, context: str, fact: str) -> Any:
        """
        Persist a fact or context snippet to Supabase.
        This method is kept for backward compatibility but should use save_summary for conversations.
        """
        data = {
            "user_id": user_id,
            "session_id": session_id,
            "context": context,
            "fact": fact,
            "content_type": "fact",
            "created_at": datetime.utcnow().isoformat()
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
            
            data = {
                "user_id": user_id,
                "session_id": session_id,
                "context": context,
                "fact": summary_data["summary"],
                "content_type": "conversation_summary",
                "metadata": {
                    "topics": summary_data["topics"],
                    "message_count": summary_data["message_count"],
                    "user_preferences": summary_data["user_preferences"],
                    "summary_type": summary_data["summary_type"]
                },
                "created_at": datetime.utcnow().isoformat()
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
        filters = {"user_id": user_id, "content_type": "conversation_summary"}
        if session_id:
            filters["session_id"] = session_id
        
        try:
            # Use Supabase client directly for ordering and limiting
            query = (
                self.db.supabase.table(self.table)
                .select("*")
                .eq("user_id", user_id)
                .eq("content_type", "conversation_summary")
            )
            
            if session_id:
                query = query.eq("session_id", session_id)
            
            query = query.order("created_at", desc=True).limit(limit)
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
            # Delete old individual facts for this session
            filters = {
                "user_id": user_id,
                "session_id": session_id,
                "content_type": "fact"
            }
            
            # Note: This would need a proper delete method in SupabaseDB
            # For now, we'll mark them as archived
            old_facts = self.get_facts(user_id, session_id)
            for fact in old_facts:
                if fact.get("content_type") == "fact":
                    # Update to mark as archived instead of deleting
                    self.db.supabase.table(self.table).update({
                        "content_type": "archived_fact",
                        "archived_at": datetime.utcnow().isoformat()
                    }).eq("id", fact.get("id")).execute()
                    
            logger.info(f"Archived {len(old_facts)} old facts for {user_id}/{session_id}")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old facts: {e}")
