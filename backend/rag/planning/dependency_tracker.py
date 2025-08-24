# backend/rag/planning/dependency_tracker.py
from __future__ import annotations
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, field

@dataclass
class DependencyTracker:
    """
    Tracks sub-questions and simple pairwise dependencies: child -> depends_on.
    Ensures we don't schedule a child before its prerequisite is marked done.
    """
    # Queue in order of insertion
    queue: List[str] = field(default_factory=list)
    # Completed sub-questions
    done: Set[str] = field(default_factory=set)
    # child -> set(parents)
    deps: Dict[str, Set[str]] = field(default_factory=dict)

    def add(self, subquestions: List[str], dependencies: List[Dict[str, str]]) -> None:
        # Add sub-questions (deduplicated)
        for s in subquestions:
            s = s.strip()
            if not s:
                continue
            if s not in self.queue and s not in self.done:
                self.queue.append(s)

        # Record dependencies
        for d in dependencies:
            child = d.get("child", "").strip()
            parent = d.get("depends_on", "").strip()
            if not child or not parent:
                continue
            if child not in self.deps:
                self.deps[child] = set()
            self.deps[child].add(parent)

    def mark_done(self, subquestion: str) -> None:
        s = subquestion.strip()
        if not s:
            return
        self.done.add(s)

    def next_ready(self) -> Optional[str]:
        """
        Pop and return the next sub-question whose dependencies are satisfied.
        If the front item isn't ready, we scan the queue to find one that is.
        """
        # Quick pass: any head ready?
        if self.queue:
            head = self.queue[0]
            if self._is_ready(head):
                return self.queue.pop(0)

        # Otherwise scan for any ready subquestion in the queue
        for idx, q in enumerate(self.queue):
            if self._is_ready(q):
                return self.queue.pop(idx)

        return None

    def _is_ready(self, subq: str) -> bool:
        reqs = self.deps.get(subq, set())
        # ready if every requirement is already done OR requirement not in our known set (treated as satisfied)
        return all((r in self.done) or (r not in self.queue) for r in reqs)

    def pending(self) -> List[str]:
        return list(self.queue)
