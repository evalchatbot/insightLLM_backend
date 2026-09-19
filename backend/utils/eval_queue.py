"""
Bounded concurrency gate for heavy evaluations.

All evaluation types (20-mark OCR, English essay, precis, outline) share ONE
global gate so a single container never runs more than ``MAX_CONCURRENT_EVALS``
heavy jobs at once. Jobs beyond the cap block on :meth:`EvalGate.acquire` — while
they wait, their job status stays ``PENDING`` ("queued"), so several PCs running
bulk at the same time line up in an orderly queue instead of overwhelming the box
(out-of-memory guards, Vision/Grok rate limits, thrashing).

The cap is read once from the ``MAX_CONCURRENT_EVALS`` environment variable
(default 6) and can be raised on a bigger container without code changes.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Dict, Optional

DEFAULT_MAX_CONCURRENT = 6


def _configured_max() -> int:
    try:
        n = int(os.getenv("MAX_CONCURRENT_EVALS", str(DEFAULT_MAX_CONCURRENT)))
    except (TypeError, ValueError):
        n = DEFAULT_MAX_CONCURRENT
    return max(1, n)


class EvalGate:
    """A counting gate that caps how many evaluations run concurrently."""

    def __init__(self, max_concurrent: int):
        self.max_concurrent = max(1, int(max_concurrent))
        self._sem = threading.BoundedSemaphore(self.max_concurrent)
        self._lock = threading.Lock()
        self._active = 0
        self._waiting = 0

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """Take a slot, blocking until one is free (or ``timeout`` seconds).

        Returns True if a slot was acquired. While blocked, the caller counts as
        "waiting" (queued); once acquired it counts as "active" (processing).
        """
        with self._lock:
            self._waiting += 1
        try:
            acquired = self._sem.acquire(timeout=timeout) if timeout is not None else self._sem.acquire()
        finally:
            with self._lock:
                self._waiting -= 1
        if acquired:
            with self._lock:
                self._active += 1
        return bool(acquired)

    def release(self) -> None:
        with self._lock:
            if self._active > 0:
                self._active -= 1
        try:
            self._sem.release()
        except ValueError:
            # Released more times than acquired — ignore rather than crash a worker.
            pass

    @contextmanager
    def slot(self, timeout: Optional[float] = None):
        """Context manager: ``with gate.slot() as got:`` acquires and always releases."""
        got = self.acquire(timeout=timeout)
        try:
            yield got
        finally:
            if got:
                self.release()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "active": self._active,
                "waiting": self._waiting,
                "max": self.max_concurrent,
            }


_gate: Optional[EvalGate] = None
_gate_lock = threading.Lock()


def get_eval_gate() -> EvalGate:
    """Return the process-wide evaluation gate (created lazily)."""
    global _gate
    if _gate is None:
        with _gate_lock:
            if _gate is None:
                _gate = EvalGate(_configured_max())
    return _gate
