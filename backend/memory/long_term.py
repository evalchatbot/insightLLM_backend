"""
Long-term memory management using Supabase.
Persists important facts, context, and user preferences.
"""
from typing import List, Dict, Any, Optional
from backend.db.supabase_client import SupabaseDB

class LongTermMemory:
    """
    Manages long-term memory by persisting key facts and context in Supabase.
    Organizes memory by user/session/context.
    """
    def __init__(self):
        self.db = SupabaseDB()
        self.table = "long_term_memory"  # Table must exist in Supabase

    def save_fact(self, user_id: str, session_id: str, context: str, fact: str) -> Any:
        """Persist a fact or context snippet to Supabase."""
        data = {
            "user_id": user_id,
            "session_id": session_id,
            "context": context,
            "fact": fact
        }
        return self.db.insert(self.table, data)

    def get_facts(self, user_id: str, session_id: Optional[str] = None, context: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve facts for a user, optionally filtered by session/context."""
        filters = {"user_id": user_id}
        if session_id:
            filters["session_id"] = session_id
        if context:
            filters["context"] = context
        res = self.db.select(self.table, filters)
        return res.data if hasattr(res, 'data') else []
