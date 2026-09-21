"""
In-memory stand-ins for external boundaries (Supabase / PostgREST query builder,
HTTP responses). They are deliberately small: just enough of the real surface that
the app code under test uses, with every call recorded so tests can assert on it.
"""

from __future__ import annotations

import copy
import itertools
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

# --------------------------------------------------------------------------------------
# Supabase / PostgREST
# --------------------------------------------------------------------------------------


@dataclass
class FakeResponse:
    data: Any
    count: Optional[int] = None


@dataclass
class RecordedQuery:
    table: str
    op: str
    columns: str
    filters: List[Tuple[str, str, Any]]
    order: List[Tuple[str, bool]]
    limit: Optional[int]
    range: Optional[Tuple[int, int]]
    payload: Any
    on_conflict: Optional[str]


def _value(row: Dict[str, Any], col: str) -> Any:
    """Column lookup supporting PostgREST JSON paths like ``metadata->>module``."""
    if "->>" in col:
        base, key = col.split("->>", 1)
        nested = row.get(base) or {}
        value = nested.get(key) if isinstance(nested, dict) else None
        return None if value is None else str(value)
    return row.get(col)


def _matches(row: Dict[str, Any], flt: Tuple[str, str, Any]) -> bool:
    col, op, val = flt
    have = _value(row, col)
    if op == "ilike":
        return isinstance(have, str) and have.lower() == str(val).lower()
    if op == "eq":
        return have == val
    if op == "neq":
        return have != val
    if op == "in":
        return have in val
    if op == "is":
        return have is val
    if have is None:
        return False
    if op == "gt":
        return have > val
    if op == "gte":
        return have >= val
    if op == "lt":
        return have < val
    if op == "lte":
        return have <= val
    raise NotImplementedError(op)


class FakeQuery:
    """Chainable query builder mimicking ``client.table(name).select(...).eq(...).execute()``."""

    def __init__(self, client: "FakeSupabaseClient", table: str) -> None:
        self._client = client
        self.table = table
        self.op = "select"
        self.columns = "*"
        self.filters: List[Tuple[str, str, Any]] = []
        self.order_by: List[Tuple[str, bool]] = []
        self.limit_n: Optional[int] = None
        self.range_: Optional[Tuple[int, int]] = None
        self.payload: Any = None
        self.on_conflict: Optional[str] = None
        self.count_mode: Optional[str] = None

    # -- operations ---------------------------------------------------------------
    def select(self, columns: str = "*", *args: Any, count: Optional[str] = None, **kwargs: Any) -> "FakeQuery":
        self.op, self.columns, self.count_mode = "select", columns, count
        return self

    def insert(self, payload: Any, *args: Any, **kwargs: Any) -> "FakeQuery":
        self.op, self.payload = "insert", payload
        return self

    def upsert(self, payload: Any, *args: Any, on_conflict: Optional[str] = None, **kwargs: Any) -> "FakeQuery":
        self.op, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def update(self, payload: Dict[str, Any], *args: Any, **kwargs: Any) -> "FakeQuery":
        self.op, self.payload = "update", payload
        return self

    def delete(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        self.op = "delete"
        return self

    # -- filters / modifiers --------------------------------------------------------
    def _f(self, col: str, op: str, val: Any) -> "FakeQuery":
        self.filters.append((col, op, val))
        return self

    def eq(self, col: str, val: Any) -> "FakeQuery":
        return self._f(col, "eq", val)

    def neq(self, col: str, val: Any) -> "FakeQuery":
        return self._f(col, "neq", val)

    def gt(self, col: str, val: Any) -> "FakeQuery":
        return self._f(col, "gt", val)

    def gte(self, col: str, val: Any) -> "FakeQuery":
        return self._f(col, "gte", val)

    def lt(self, col: str, val: Any) -> "FakeQuery":
        return self._f(col, "lt", val)

    def lte(self, col: str, val: Any) -> "FakeQuery":
        return self._f(col, "lte", val)

    def in_(self, col: str, vals: Any) -> "FakeQuery":
        return self._f(col, "in", list(vals))

    def is_(self, col: str, val: Any) -> "FakeQuery":
        return self._f(col, "is", val)

    def ilike(self, col: str, pattern: str) -> "FakeQuery":
        return self._f(col, "ilike", pattern)  # exact, case-insensitive (no % wildcards needed yet)

    def filter(self, col: str, op: str, val: Any) -> "FakeQuery":
        return self._f(col, op, val)

    def order(self, col: str, desc: bool = False, **kwargs: Any) -> "FakeQuery":
        self.order_by.append((col, desc))
        return self

    def limit(self, n: int, **kwargs: Any) -> "FakeQuery":
        self.limit_n = n
        return self

    def range(self, start: int, end: int, **kwargs: Any) -> "FakeQuery":
        self.range_ = (start, end)
        return self

    # -- execution ------------------------------------------------------------------
    def record(self) -> RecordedQuery:
        return RecordedQuery(
            table=self.table,
            op=self.op,
            columns=self.columns,
            filters=list(self.filters),
            order=list(self.order_by),
            limit=self.limit_n,
            range=self.range_,
            payload=copy.deepcopy(self.payload),
            on_conflict=self.on_conflict,
        )

    def execute(self) -> FakeResponse:
        rec = self.record()
        self._client.queries.append(rec)
        for predicate, exc in self._client.failures:
            if predicate(rec):
                raise exc

        rows = self._client.tables.setdefault(self.table, [])
        matched = [r for r in rows if all(_matches(r, f) for f in self.filters)]

        if self.op == "select":
            out = [dict(r) for r in matched]
            for col, desc in reversed(self.order_by):
                out.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
            if self.range_ is not None:
                out = out[self.range_[0] : self.range_[1] + 1]
            if self.limit_n is not None:
                out = out[: self.limit_n]
            cols = [c.strip() for c in self.columns.split(",")] if self.columns.strip() != "*" else None
            if cols:
                out = [{c: r.get(c) for c in cols} for r in out]
            return FakeResponse(out, count=len(matched) if self.count_mode == "exact" else None)

        if self.op in ("insert", "upsert"):
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            written = []
            for item in items:
                item = dict(item)
                item.setdefault("id", str(uuid.uuid4()))
                if self.op == "upsert" and self.on_conflict:
                    key = self.on_conflict
                    existing = next((r for r in rows if r.get(key) == item.get(key)), None)
                    if existing is not None:
                        existing.update({k: v for k, v in item.items() if k != "id"})
                        written.append(dict(existing))
                        continue
                rows.append(item)
                written.append(dict(item))
            return FakeResponse(written)

        if self.op == "update":
            for r in matched:
                r.update(self.payload)
            return FakeResponse([dict(r) for r in matched])

        if self.op == "delete":
            for r in matched:
                rows.remove(r)
            return FakeResponse([dict(r) for r in matched])

        raise NotImplementedError(self.op)


class FakeRPC:
    def __init__(self, client: "FakeSupabaseClient", name: str, params: Dict[str, Any]) -> None:
        self._client, self.name, self.params = client, name, params

    def execute(self) -> FakeResponse:
        self._client.rpc_calls.append((self.name, copy.deepcopy(self.params)))
        result = self._client.rpc_results.get(self.name)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            result = result(self.params)
        return FakeResponse(result)


@dataclass
class FakeSupabaseClient:
    """Stand-in for ``supabase.Client`` (table/rpc) backed by plain dict rows."""

    tables: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    rpc_results: Dict[str, Any] = field(default_factory=dict)
    queries: List[RecordedQuery] = field(default_factory=list)
    rpc_calls: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    failures: List[Tuple[Callable[[RecordedQuery], bool], Exception]] = field(default_factory=list)

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    # supabase-py also exposes `.from_()`
    from_ = table

    def rpc(self, name: str, params: Optional[Dict[str, Any]] = None) -> FakeRPC:
        return FakeRPC(self, name, params or {})

    def fail_when(self, predicate: Callable[[RecordedQuery], bool], exc: Exception) -> None:
        self.failures.append((predicate, exc))


def supabase_service_with(fake: FakeSupabaseClient):
    """A real ``SupabaseService`` whose PostgREST client is the in-memory fake."""
    from backend.db.supabase_service import SupabaseService

    svc = object.__new__(SupabaseService)
    svc.supabase = fake
    return svc


def supabase_db_with(fake: FakeSupabaseClient):
    """A real ``SupabaseDB`` wrapper (users/books routes) backed by the fake client."""
    from backend.db.supabase_client import SupabaseDB

    db = object.__new__(SupabaseDB)
    db.client = fake
    db._embedding_dimensions = None
    return db


# --------------------------------------------------------------------------------------
# HTTP (requests)
# --------------------------------------------------------------------------------------


def make_requests_response(status: int = 200, body: Any = None, *, text: Optional[str] = None) -> requests.Response:
    """Build a real ``requests.Response`` without touching the network."""
    resp = requests.Response()
    resp.status_code = status
    if text is not None:
        resp._content = text.encode("utf-8")
    else:
        resp._content = json.dumps(body if body is not None else {}).encode("utf-8")
    resp.encoding = "utf-8"
    resp.headers["Content-Type"] = "application/json"
    return resp


class RecordingPost:
    """Callable replacement for ``requests.post`` that replays scripted responses."""

    def __init__(self, *responses: Any) -> None:
        self._responses = itertools.chain(responses, itertools.repeat(None))
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"url": url, **kwargs})
        nxt = next(self._responses)
        if nxt is None:
            raise AssertionError(f"unexpected extra POST to {url}")
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def grok_completion(content: str, *, finish_reason: str = "stop", usage: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """An OpenAI/xAI-style chat completion payload."""
    payload: Dict[str, Any] = {
        "id": "cmpl-test",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload
