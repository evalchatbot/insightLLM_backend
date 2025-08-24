"""
Short-term memory management using LangGraph's InMemoryStore.
Organizes context by (user_id, session_id).
"""
from typing import List, Dict, Tuple
from langchain.storage import InMemoryStore

class ShortTermMemory:
    """
    Manages short-term conversational memory using LangGraph's InMemoryStore.
    Organizes memory by (user_id, session_id).
    """
    def __init__(self, window_size: int = 10):
        self.store: Dict[Tuple[str, str], InMemoryStore] = {}
        self.window_size = window_size

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

    def get_recent_messages(self, user_id: str, session_id: str) -> List[dict]:
        store = self.get_store(user_id, session_id)
        keys = list(store.yield_keys())
        if not keys:
            return []
        return store.mget(keys)

    def clear(self, user_id: str, session_id: str) -> None:
        key = (user_id, session_id)
        if key in self.store:
            del self.store[key]
