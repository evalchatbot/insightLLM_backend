from __future__ import annotations
import time
from typing import Any, Dict, Tuple, Optional

class TTLCache:
    def __init__(self, ttl_s: int = 600) -> None:
        self.ttl_s = ttl_s
        self._store: Dict[str, Tuple[float, Any]] = {}

    def _now(self) -> float:
        return time.time()

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if self._now() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (self._now() + self.ttl_s, value)

    def clear(self) -> None:
        self._store.clear()
