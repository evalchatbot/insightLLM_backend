"""/conversations contract tests against the real SupabaseService + in-memory PostgREST fake."""

from __future__ import annotations

import pytest

from support.fakes import FakeSupabaseClient, supabase_service_with

pytestmark = pytest.mark.api


def conv(cid, user, title="Chat", updated="2026-03-01T10:00:00"):
    return {
        "id": cid,
        "user_id": user,
        "chat_id": f"chat-{cid}",
        "title": title,
        "icon": None,
        "is_pinned": False,
        "created_at": "2026-03-01T09:00:00",
        "updated_at": updated,
    }


@pytest.fixture
def db(monkeypatch):
    from backend.api.routes import conversations

    fake = FakeSupabaseClient(
        tables={
            "users": [{"id": "alice"}, {"id": "bob"}],
            "conversations": [
                conv("c1", "alice", "Old", updated="2026-03-01T10:00:00"),
                conv("c2", "alice", "Newer", updated="2026-03-02T10:00:00"),
                conv("c3", "bob", "Bob's"),
            ],
            "messages": [
                {"id": "m2", "conversation_id": "c1", "user_prompt": "Q2", "llm_response": "A2", "created_at": "2026-03-01T09:05:00"},
                {"id": "m1", "conversation_id": "c1", "user_prompt": "Q1", "llm_response": "A1", "created_at": "2026-03-01T09:01:00"},
            ],
        }
    )
    monkeypatch.setattr(conversations, "supabase_service", supabase_service_with(fake))
    return fake


def test_list_is_scoped_to_user_and_newest_first(client, db):
    body = client.get("/conversations/", params={"user_id": "alice"}).json()
    assert body["total"] == 2
    assert [c["id"] for c in body["conversations"]] == ["c2", "c1"]


@pytest.mark.parametrize("params", [{}, {"user_id": "alice", "limit": 0}, {"user_id": "alice", "limit": 101}])
def test_list_validation(client, db, params):
    assert client.get("/conversations/", params=params).status_code == 422


def test_get_conversation_with_messages_in_chronological_order(client, db):
    body = client.get("/conversations/c1", params={"user_id": "alice"}).json()
    assert body["conversation"]["title"] == "Old"
    assert [m["id"] for m in body["messages"]] == ["m1", "m2"]


def test_other_users_conversation_is_404(client, db):
    assert client.get("/conversations/c3", params={"user_id": "alice"}).status_code == 404
    assert client.get("/conversations/missing").status_code == 404


def test_messages_pagination(client, db):
    resp = client.get("/conversations/c1/messages", params={"limit": 1, "offset": 1})
    assert [m["id"] for m in resp.json()] == ["m2"]
    assert db.queries[-1].range == (1, 1)


def test_add_user_then_assistant_message_fills_one_row(client, db):
    q = client.post("/conversations/c2/messages", json={"sender": "user", "message": "What is federalism?"})
    assert q.status_code == 200
    a = client.post("/conversations/c2/messages", json={"sender": "assistant", "message": "Power sharing."})
    assert a.status_code == 200
    rows = [m for m in db.tables["messages"] if m["conversation_id"] == "c2"]
    assert len(rows) == 1
    assert rows[0]["user_prompt"] == "What is federalism?"
    assert rows[0]["llm_response"] == "Power sharing."


def test_add_message_validates_sender_and_conversation(client, db):
    assert client.post("/conversations/c2/messages", json={"sender": "system", "message": "x"}).status_code == 400
    assert client.post("/conversations/nope/messages", json={"sender": "user", "message": "x"}).status_code == 404


def test_update_conversation(client, db):
    resp = client.put("/conversations/c1", json={"title": "Renamed", "is_pinned": True})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed"
    assert resp.json()["is_pinned"] is True


def test_update_without_changes_returns_existing(client, db):
    resp = client.put("/conversations/c1", json={})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Old"
    assert all(q.op != "update" for q in db.queries)


def test_update_missing_is_404(client, db):
    assert client.put("/conversations/nope", json={"title": "x"}).status_code == 404


def test_delete_scoped_to_owner(client, db):
    assert client.delete("/conversations/c3", params={"user_id": "alice"}).status_code == 404
    assert client.delete("/conversations/c1", params={"user_id": "alice"}).json() == {"message": "Conversation deleted successfully"}
    assert client.delete("/conversations/c1").status_code == 404


def test_info_counts_messages(client, db):
    body = client.get("/conversations/c1/info").json()
    assert body["actual_message_count"] == 2
    assert body["is_pinned"] is False


def test_new_chat_for_known_user(client, db):
    resp = client.post("/conversations/new-chat", json={"user_id": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "alice"
    assert body["title"] == "New Chat"
    assert body["chat_id"]


def test_new_chat_with_no_users_at_all_is_400(client, db):
    db.tables["users"].clear()
    resp = client.post("/conversations/new-chat", json={"user_id": "ghost"})
    assert resp.status_code == 400


@pytest.mark.xfail(
    strict=True,
    reason="BUG: SupabaseService.get_valid_user_id falls back to an arbitrary existing user, so a chat "
    "requested for an unknown user_id is silently created under someone else's account",
)
def test_new_chat_for_unknown_user_is_rejected(client, db):
    before = len(db.tables["conversations"])
    resp = client.post("/conversations/new-chat", json={"user_id": "ghost"})
    assert resp.status_code == 400
    assert len(db.tables["conversations"]) == before


@pytest.mark.xfail(
    strict=True,
    reason="BUG: /conversations/auto-title calls create_conversation_with_title(first_question=, first_answer=) "
    "but the agent signature is (question, answer) -> TypeError -> always 500",
)
def test_auto_title_creates_titled_conversation(client, db, monkeypatch):
    from backend.api.routes import conversations

    async def fake_title(question, answer):
        return "Federalism Explained"

    monkeypatch.setattr(conversations.chatbot_agent, "db_service", conversations.supabase_service)
    monkeypatch.setattr(conversations.chatbot_agent, "_generate_conversation_title", fake_title)
    resp = client.post("/conversations/auto-title", json={"user_id": "alice", "question": "Q?", "answer": "A."})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Federalism Explained"
