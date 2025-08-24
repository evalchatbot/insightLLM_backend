from __future__ import annotations
from typing import Dict

class Metrics:
    def __init__(self) -> None:
        self.counters: Dict[str, int] = {}
        self.timers_ms: Dict[str, int] = {}

    def inc(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    def observe_ms(self, key: str, ms: int) -> None:
        self.timers_ms[key] = self.timers_ms.get(key, 0) + ms

metrics = Metrics()
