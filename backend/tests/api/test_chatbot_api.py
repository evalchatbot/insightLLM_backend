"""
/chatbot and /assistant contract tests.

The real ``ChatbotAgent`` runs (question analysis, prompt building, memory bookkeeping,
SSE framing); only the LLM client and the Supabase-backed long-term memory are faked.
"""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.api

TITLE_SYSTEM = "You craft short, exam-focused chat titles."


class FakeLLM:
    """Stands in for StreamingLLMClient (Groq)."""

    def __init__(self, chunks=("Federalism ", "divides ", "power."), fail=None):
        self.chunks = list(chunks)
        self.fail = fail
        self.prompts = []

    async def generate_complete(self, prompt, *, temperature=0.4, max_tokens=2048, system_message=None):
        self.prompts.append({"prompt": prompt, "system": system_message})
        if self.fail:
            raise self.fail
        if system_message == TITLE_SYSTEM:
            return '"Federalism In Pakistan"\n', {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
        return "".join(self.chunks), {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}

    async def generate_stream(self, prompt, *, temperature=0.4, max_tokens=2048, system_message=None):
        self.prompts.append({"prompt": prompt, "system": system_message, "stream": True})
        if self.fail:
            raise self.fail
        for chunk in self.chunks:
            yield chunk, None
        yield None, {"prompt_tokens": 99, "completion_tokens": 7, "total_tokens": 106}


class FakeLongTerm:
    def __init__(self):
        self.facts = []

    def save_fact(self, user_id, session_id, context, fact):
        self.facts.append((user_id, session_id, fact))

    async def save_conversation_summary(self, *args, **kwargs):
        return None

    async def cleanup_old_facts(self, *args, **kwargs):
        return None


class FakeConversationDB:
    """The subset of SupabaseService the agent uses for conversation persistence."""

    def __init__(self, title="New Chat"):
        self.title = title
        self.pairs = []
        self.updates = []

    def add_message_pair(self, conversation_id, question, answer):
        self.pairs.append((conversation_id, question, answer))

    def get_conversation_by_id(self, conversation_id, user_id=None):
        return {"id": conversation_id, "title": self.title}

    def update_conversation(self, conversation_id, updates):
        self.updates.append((conversation_id, updates))
        return True

    def get_recent_conversation_messages(self, conversation_id, limit=8):
        return [{"user_prompt": "Earlier question?", "llm_response": "Earlier answer.", "created_at": "t"}]


@pytest.fixture
def llm(monkeypatch):
    from backend.api.routes import assistant, chatbot

    fake = FakeLLM()
    for agent in (chatbot.agent, assistant.chatbot_agent):
        monkeypatch.setattr(agent, "_streaming_client", fake)
        monkeypatch.setattr(agent, "long_term", FakeLongTerm())
        monkeypatch.setattr(agent, "db_service", None)
    return fake


def _req(question="Discuss the challenges of federalism in Pakistan.", **extra):
    return {"user_id": "user-123456789", "session_id": f"s-{uuid.uuid4().hex}", "question": question, **extra}


def _sse_events(text):
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block:
            assert block.startswith("data: "), block
            events.append(json.loads(block[len("data: "):]))
    return events


# ---------------------------------------------------------------- capabilities


def test_capabilities(client):
    body = client.get("/chatbot/capabilities").json()
    assert body["agent_type"] == "single_llm"
    assert body["supports_streaming"] is True
    assert body["rag_enabled"] is False
    assert body["memory"]["summarisation_threshold"] == 5


# ---------------------------------------------------------------- ask


def test_ask_returns_answer_with_analysis_and_title(client, llm):
    resp = client.post("/chatbot/ask", json=_req())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "Federalism divides power."
    assert body["sources"] == []
    assert body["context"] == []  # fresh session -> no history
    meta = body["metadata"]
    assert meta["mode"] == "single_llm"
    assert meta["system_prompt"] == "css-pol-sci.v3"
    assert meta["question_analysis"]["mode"] == "essay"
    assert "discuss the major dimensions of the topic" in meta["question_analysis"]["directives"]
    assert meta["token_usage"]["total_tokens"] == 150
    assert meta["suggested_title"] == "Federalism In Pakistan"

    answer_prompt = llm.prompts[0]
    assert "Exam Question:" in answer_prompt["prompt"]
    assert "Discuss the challenges of federalism in Pakistan." in answer_prompt["prompt"]
    assert answer_prompt["system"].startswith("System Prompt: Pakistani Competitive Exam Mentor")


def test_ask_greeting_uses_brief_mode(client, llm):
    body = client.post("/chatbot/ask", json=_req("hello there")).json()
    assert body["metadata"]["question_analysis"]["mode"] == "brief"
    assert "Generate a concise, high-quality response" in llm.prompts[0]["prompt"]


def test_ask_remembers_session_history(client, llm):
    req = _req()
    client.post("/chatbot/ask", json=req)
    second = client.post("/chatbot/ask", json={**req, "question": "Why does it matter?"}).json()
    assert [m["sender"] for m in second["context"]] == ["user", "assistant"]
    assert "Recent exchange (latest last):" in llm.prompts[-2]["prompt"]


def test_ask_with_conversation_persists_and_titles_it(client, llm, monkeypatch):
    from backend.api.routes import chatbot

    db = FakeConversationDB(title="New Chat")
    monkeypatch.setattr(chatbot.agent, "db_service", db)
    body = client.post("/chatbot/ask", json=_req(conversation_id="conv-1")).json()
    assert db.pairs == [("conv-1", "Discuss the challenges of federalism in Pakistan.", "Federalism divides power.")]
    assert db.updates == [("conv-1", {"title": "Federalism In Pakistan"})]
    assert body["metadata"]["conversation_id"] == "conv-1"
    assert body["metadata"]["conversation_title"] == "Federalism In Pakistan"
    # history comes from the conversation table, not the in-memory session
    assert [m["message"] for m in body["context"]] == ["Earlier question?", "Earlier answer."]


def test_ask_keeps_existing_conversation_title(client, llm, monkeypatch):
    from backend.api.routes import chatbot

    db = FakeConversationDB(title="Judicial Activism")
    monkeypatch.setattr(chatbot.agent, "db_service", db)
    body = client.post("/chatbot/ask", json=_req(conversation_id="conv-2")).json()
    assert db.updates == []
    assert body["metadata"]["conversation_title"] == "Judicial Activism"


def test_ask_sanitises_pasted_transcript(client, llm):
    raw = "User: hi\nAssistant: hello\nCurrent question:\nExplain the doctrine of necessity"
    client.post("/chatbot/ask", json=_req(raw))
    assert "Explain the doctrine of necessity" in llm.prompts[0]["prompt"]
    assert "Assistant: hello" not in llm.prompts[0]["prompt"]


def test_ask_multi_delegates_to_ask(client, llm):
    body = client.post("/chatbot/ask-multi", json=_req()).json()
    assert body["answer"] == "Federalism divides power."
    assert body["metadata"]["mode"] == "single_llm"


@pytest.mark.parametrize("missing", ["user_id", "session_id", "question"])
def test_ask_requires_fields(client, llm, missing):
    payload = _req()
    payload.pop(missing)
    assert client.post("/chatbot/ask", json=payload).status_code == 422


def test_ask_llm_failure_is_500(client, llm):
    llm.fail = RuntimeError("GROQ_API_KEY not set")
    resp = client.post("/chatbot/ask", json=_req())
    assert resp.status_code == 500
    assert resp.json()["detail"] == "GROQ_API_KEY not set"


def test_ask_without_llm_key_is_500(client, monkeypatch):
    """No fake installed: the real client factory refuses to run without GROQ_API_KEY."""
    from backend.api.routes import chatbot

    monkeypatch.setattr(chatbot.agent, "_streaming_client", None)
    monkeypatch.setattr(chatbot.agent, "long_term", FakeLongTerm())
    from backend.rag.config import get_rag_settings

    get_rag_settings.cache_clear()
    resp = client.post("/chatbot/ask", json=_req())
    assert resp.status_code == 500
    assert resp.json()["detail"] == "GROQ_API_KEY not set"


# ---------------------------------------------------------------- streaming


def test_ask_stream_emits_sse_chunks_then_complete(client, llm):
    resp = client.post("/chatbot/ask-stream", json=_req())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    events = _sse_events(resp.text)
    assert [e["type"] for e in events] == ["chunk", "chunk", "chunk", "complete"]
    assert "".join(e["content"] for e in events[:-1]) == "Federalism divides power."
    final = events[-1]
    assert final["answer"] == "Federalism divides power."
    assert final["sources"] == [] and final["citations"] == []
    meta = final["metadata"]
    assert meta["mode"] == "single_llm_stream"
    assert meta["token_usage"] == {"prompt_tokens": 99, "completion_tokens": 7, "total_tokens": 106}
    assert meta["question_analysis"]["mode"] == "essay"
    assert meta["suggested_title"] == "Federalism In Pakistan"


def test_ask_stream_keeps_unicode_intact(client, llm):
    llm.chunks = ["Qaid-e-Azam ", "— “quote” ", "اردو"]
    events = _sse_events(client.post("/chatbot/ask-stream", json=_req()).text)
    assert events[-1]["answer"] == "Qaid-e-Azam — “quote” اردو"


def test_ask_stream_reports_errors_as_event(client, llm):
    llm.fail = RuntimeError("upstream 503")
    resp = client.post("/chatbot/ask-stream", json=_req())
    assert resp.status_code == 200  # headers already sent; error travels in-band
    assert _sse_events(resp.text) == [{"type": "error", "error": "upstream 503"}]


def test_ask_stream_passes_conversation_id_through(client, llm):
    events = _sse_events(client.post("/chatbot/ask-stream", json=_req(conversation_id="c-9")).text)
    assert events[-1]["metadata"]["conversation_id"] == "c-9"


# ---------------------------------------------------------------- assistant


def test_assistant_ask_annotates_router_metadata(client, llm):
    body = client.post("/assistant/ask", json=_req()).json()
    assert body["answer"] == "Federalism divides power."
    assert body["metadata"]["router"] == "single_llm"
    assert body["metadata"]["routed_to"] == "chatbot"


def test_assistant_failure_is_500(client, llm):
    llm.fail = ValueError("boom")
    assert client.post("/assistant/ask", json=_req()).status_code == 500
