"""/user (dev-token + JWT-protected sessions), /books and /api/documents contract tests."""

from __future__ import annotations

import time

import pytest
from jose import jwt

from support.fakes import FakeSupabaseClient, supabase_db_with, supabase_service_with
from support.pdfs import text_pdf

pytestmark = pytest.mark.api

SECRET = "test-jwt-secret-not-for-production"


def supabase_token(sub="user-1", *, secret=SECRET, exp_in=3600, aud="authenticated", iss="/auth/v1", **extra):
    claims = {"sub": sub, "email": f"{sub}@example.com", "aud": aud, "iss": iss, "exp": int(time.time()) + exp_in}
    claims.update(extra)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm="HS256")


@pytest.fixture
def users_db(monkeypatch):
    from backend.api.routes import users

    fake = FakeSupabaseClient(tables={"sessions": []})
    monkeypatch.setattr(users, "db", supabase_db_with(fake))
    return fake


# ---------------------------------------------------------------- dev token


def test_dev_token_is_issued_outside_production(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    resp = client.post("/user/dev-token", json={"user_id": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"], audience="authenticated")
    assert claims["sub"] == "alice"
    assert claims["email"] == "alice@test.com"


def test_dev_token_hidden_in_production(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    resp = client.post("/user/dev-token", json={"user_id": "alice"})
    assert resp.status_code == 404


def test_dev_token_requires_user_id(client):
    assert client.post("/user/dev-token", json={}).status_code == 422


@pytest.mark.xfail(
    strict=True,
    reason="BUG: /user/dev-token signs iss=SUPABASE_ISSUER env (default 'supabase') but get_current_user "
    "verifies iss=config.SUPABASE_ISSUER ('/auth/v1'), so dev tokens are always rejected with 401",
)
def test_dev_token_is_accepted_by_protected_routes(client, users_db, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    token = client.post("/user/dev-token", json={"user_id": "alice"}).json()["access_token"]
    resp = client.post("/user/session/create", json={}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# ---------------------------------------------------------------- JWT-protected sessions


def test_session_create_requires_bearer_token(client, users_db):
    resp = client.post("/user/session/create", json={})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing Bearer token"


@pytest.mark.parametrize(
    "token",
    [
        supabase_token(exp_in=-60),  # expired
        supabase_token(secret="some-other-secret"),  # wrong signature
        supabase_token(aud="anon"),  # wrong audience
        supabase_token(iss="https://evil.example/auth/v1"),  # wrong issuer
        "not-a-jwt",
    ],
    ids=["expired", "wrong-secret", "wrong-audience", "wrong-issuer", "garbage"],
)
def test_session_create_rejects_bad_tokens(client, users_db, token):
    resp = client.post("/user/session/create", json={}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired token"
    assert users_db.tables["sessions"] == []


def test_session_create_rejects_token_without_subject(client, users_db):
    token = supabase_token(sub=None)
    resp = client.post("/user/session/create", json={}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token missing subject"


def test_session_create_trusts_token_not_body(client, users_db):
    resp = client.post(
        "/user/session/create",
        json={"user_id": "mallory"},
        headers={"Authorization": f"Bearer {supabase_token('alice')}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "alice"
    assert body["session_id"].startswith("sess_") and body["session_id"].endswith("_alice")
    (row,) = users_db.tables["sessions"]
    assert row["user_id"] == "alice" and row["id"] == body["session_id"]


def test_get_session_roundtrip_and_404(client, users_db):
    auth = {"Authorization": f"Bearer {supabase_token('alice')}"}
    created = client.post("/user/session/create", json={}, headers=auth).json()
    got = client.get(f"/user/session/{created['session_id']}", headers=auth)
    assert got.status_code == 200
    assert got.json()["user_id"] == "alice"
    assert client.get("/user/session/does-not-exist", headers=auth).status_code == 404


def test_get_session_requires_auth(client, users_db):
    assert client.get("/user/session/x").status_code == 401


# ---------------------------------------------------------------- books


@pytest.fixture
def books_db(monkeypatch):
    from backend.api.routes import books

    fake = FakeSupabaseClient(
        tables={
            "books": [
                {"id": "b1", "title": "Constitution 1973", "author": "", "genre": "Law", "file_url": ""},
                {"id": "b2", "title": "Foreign Policy", "author": "X", "genre": "IR", "file_url": ""},
                {"id": "b3", "title": "Torts", "author": "Y", "genre": "Law", "file_url": ""},
            ]
        }
    )
    monkeypatch.setattr(books, "db", supabase_db_with(fake))
    return fake


def test_book_genres_are_distinct_and_sorted(client, books_db):
    assert client.get("/books/genres").json() == {"genres": ["IR", "Law"]}


def test_books_by_genre(client, books_db):
    body = client.get("/books/Law").json()
    assert [b["id"] for b in body["books"]] == ["b1", "b3"]


def test_books_empty_results(client, books_db):
    books_db.tables["books"].clear()
    assert client.get("/books/genres").json() == {"genres": []}
    assert client.get("/books/Law").json() == {"books": []}


# ---------------------------------------------------------------- documents


class FakeProcessor:
    def __init__(self, chunks):
        self.chunks = chunks
        self.paths = []

    def process_document(self, path):
        with open(path, "rb") as fh:
            self.paths.append((path, fh.read(4)))
        return [dict(c) for c in self.chunks]


CHUNKS = [
    {"content": "c1", "page_start": 1, "page_end": 1, "chunk_index": 0, "embedding": [0.1], "metadata": {}},
    {"content": "c2", "page_start": 1, "page_end": 3, "chunk_index": 1, "embedding": [0.2], "metadata": {}},
]


@pytest.fixture
def documents(app):
    from backend.api.routes import ingest

    fake_db = FakeSupabaseClient()
    processor = FakeProcessor(CHUNKS)
    app.dependency_overrides[ingest.get_document_processor] = lambda: processor
    app.dependency_overrides[ingest.get_supabase_service] = lambda: supabase_service_with(fake_db)
    return processor, fake_db


def test_document_upload_requires_service_role_key(client, app):
    from backend.api.routes import ingest

    app.dependency_overrides[ingest.get_document_processor] = lambda: FakeProcessor(CHUNKS)
    resp = client.post("/api/documents/upload", files={"file": ("a.pdf", text_pdf(), "application/pdf")})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Missing required environment variables"


def test_document_upload_rejects_non_pdf(client, documents):
    resp = client.post("/api/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert resp.status_code == 400
    assert documents[0].paths == []


def test_document_upload_stores_book_and_chunks_and_cleans_temp(client, documents):
    import os

    processor, fake_db = documents
    resp = client.post(
        "/api/documents/upload",
        files={"file": ("Pakistan Affairs.pdf", text_pdf(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    (book,) = fake_db.tables["books"]
    assert body == {"book_id": book["id"], "num_chunks": 2, "message": "Document ingested successfully"}
    assert book["title"] == "Pakistan Affairs"
    assert book["author"] == "Unknown Author"
    assert book["total_pages"] == 3
    assert {c["book_id"] for c in fake_db.tables["document_chunks"]} == {book["id"]}
    (path, magic), = processor.paths
    assert magic == b"%PDF"
    assert not os.path.exists(path)


def test_document_upload_with_no_chunks_is_500(client, documents):
    documents[0].chunks = []
    resp = client.post("/api/documents/upload", files={"file": ("a.pdf", text_pdf(), "application/pdf")})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to process document"
