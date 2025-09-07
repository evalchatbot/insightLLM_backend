"""
Short-term memory management using LangGraph's InMemoryStore.
Organizes context by (user_id, session_id).
"""
from typing import List, Dict, Tuple
from langchain.storage import InMemoryStore
import logging

logger = logging.getLogger(__name__)

class ShortTermMemory:
    """
    Manages short-term conversational memory using LangGraph's InMemoryStore.
    Organizes memory by (user_id, session_id).
    """
    def __init__(self, window_size: int = 10, summarization_threshold: int = 5):
        self.store: Dict[Tuple[str, str], InMemoryStore] = {}
        self.window_size = window_size
        self.summarization_threshold = summarization_threshold
        # Track conversation counts for summarization
        self.conversation_counts: Dict[Tuple[str, str], int] = {}

    def get_store(self, user_id: str, session_id: str) -> InMemoryStore:
        key = (user_id, session_id)
        if key not in self.store:
            self.store[key] = InMemoryStore()  # window size enforcement must be handled manually
        return self.store[key]

    def add_message(self, user_id: str, session_id: str, message: dict) -> None:
        store = self.get_store(user_id, session_id)
        import time
        key = str(time.time_ns())
        store.mset([(key, message)])
        
        # Track conversation count for summarization
        session_key = (user_id, session_id)
        if session_key not in self.conversation_counts:
            self.conversation_counts[session_key] = 0
        self.conversation_counts[session_key] += 1

    def get_recent_messages(self, user_id: str, session_id: str) -> List[dict]:
        store = self.get_store(user_id, session_id)
        keys = list(store.yield_keys())
        if not keys:
            return []
        return store.mget(keys)

    def get_conversation_count(self, user_id: str, session_id: str) -> int:
        """Get the current conversation count for a session."""
        session_key = (user_id, session_id)
        return self.conversation_counts.get(session_key, 0)
    
    def should_summarize(self, user_id: str, session_id: str) -> bool:
        """Check if conversation should be summarized."""
        count = self.get_conversation_count(user_id, session_id)
        return count >= self.summarization_threshold and count % self.summarization_threshold == 0
    
    def reset_conversation_count(self, user_id: str, session_id: str) -> None:
        """Reset conversation count after summarization."""
        session_key = (user_id, session_id)
        self.conversation_counts[session_key] = 0
    
    def clear(self, user_id: str, session_id: str) -> None:
        key = (user_id, session_id)
        if key in self.store:
            del self.store[key]
        # Also clear conversation count
        if key in self.conversation_counts:
            del self.conversation_counts[key]
