"""App wiring: import, route table, health endpoints, OpenAPI generation."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from fastapi.routing import APIRoute

from support.env import REMOVED_ENV, REPO_ROOT

pytestmark = pytest.mark.api

EXPECTED_ROUTES = {
    ("GET", "/"),
    ("GET", "/health"),
    # OCR (20-marks rubric)
    ("POST", "/api/ocr/annotate"),
    ("POST", "/api/ocr/annotate/json"),
    ("GET", "/api/ocr/subjects"),
    ("GET", "/api/ocr/progress/{request_id}"),
    ("POST", "/api/ocr/submit"),
    ("GET", "/api/ocr/job/{job_id}"),
    ("POST", "/api/ocr/job/{job_id}/cancel"),
    ("GET", "/api/ocr/job/{job_id}/result"),
    ("POST", "/api/ocr-regular/annotate"),
    ("POST", "/api/ocr-regular/annotate/json"),
    ("GET", "/api/ocr-regular/subjects"),
    # Essay / outline / precis job pipelines
    *{
        (method, f"/api/{kind}/{suffix}")
        for kind in ("essay", "outline", "precis")
        for method, suffix in (
            ("POST", "submit"),
            ("GET", "status/{job_id}"),
            ("GET", "download/{job_id}"),
            ("GET", "result/{job_id}"),
        )
    },
    # Fact Book
    ("GET", "/api/factbook/editorials"),
    ("GET", "/api/factbook/editorial-dates"),
    ("GET", "/api/factbook/topics"),
    ("GET", "/api/factbook/editorials/by-topic"),
    ("POST", "/api/factbook/digest"),
    ("POST", "/api/factbook/sync/daily"),
    ("POST", "/api/factbook/sync/backfill"),
    # Quiz
    ("GET", "/quiz/genres"),
    ("GET", "/quiz/mcqs"),
    ("POST", "/quiz/sync/current-affairs/daily"),
    ("POST", "/quiz/sync/current-affairs/backfill"),
    # Chat
    ("POST", "/chatbot/ask"),
    ("POST", "/chatbot/ask-multi"),
    ("POST", "/chatbot/ask-stream"),
    ("GET", "/chatbot/capabilities"),
    ("POST", "/assistant/ask"),
    # Conversations
    ("POST", "/conversations/new-chat"),
    ("POST", "/conversations/"),
    ("POST", "/conversations/auto-title"),
    ("GET", "/conversations/"),
    ("GET", "/conversations/{conversation_id}"),
    ("GET", "/conversations/{conversation_id}/messages"),
    ("POST", "/conversations/{conversation_id}/messages"),
    ("PUT", "/conversations/{conversation_id}"),
    ("DELETE", "/conversations/{conversation_id}"),
    ("GET", "/conversations/{conversation_id}/info"),
    # Documents / books / users
    ("POST", "/api/documents/upload"),
    ("GET", "/books/genres"),
    ("GET", "/books/{genre}"),
    ("POST", "/user/dev-token"),
    ("POST", "/user/session/create"),
    ("GET", "/user/session/{session_id}"),
}


def _registered(app):
    return {(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods}


def test_every_expected_route_is_registered(app):
    missing = EXPECTED_ROUTES - _registered(app)
    assert not missing, f"routes missing from the app: {sorted(missing)}"


def test_no_unexpected_routes_were_added(app):
    # Forces this contract list to be updated deliberately when the API surface grows.
    extra = _registered(app) - EXPECTED_ROUTES
    assert not extra, f"new routes need a contract test entry: {sorted(extra)}"


def test_route_paths_are_unique_per_method(app):
    pairs = [(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods]
    assert len(pairs) == len(set(pairs))


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "NotebookLM Backend is running"}


def test_health_reports_status_and_iso_timestamp(client):
    from datetime import datetime

    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    datetime.fromisoformat(body["timestamp"])  # raises if not ISO-8601


def test_openapi_schema_generates(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "NotebookLM Backend"
    assert "/api/factbook/digest" in schema["paths"]
    assert "/chatbot/ask-stream" in schema["paths"]


def test_docs_page_served(client):
    assert client.get("/docs").status_code == 200


def test_unknown_route_is_404(client):
    assert client.get("/definitely-not-a-route").status_code == 404


def test_cors_allows_any_origin(client):
    resp = client.options(
        "/health",
        headers={"Origin": "https://lca-portal.example", "Access-Control-Request-Method": "GET"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") in ("*", "https://lca-portal.example")


def test_startup_is_not_run_by_plain_testclient(app):
    """Sanity check for the suite itself: the Fact Book scheduler is disabled in tests."""
    from backend import config

    assert config.FACTBOOK_SCHEDULER_ENABLED is False


def _clean_env():
    env = {k: v for k, v in os.environ.items() if k not in REMOVED_ENV and not k.startswith("SUPABASE_")}
    env["PYTHONIOENCODING"] = "utf-8"
    env["FACTBOOK_SCHEDULER_ENABLED"] = "false"
    return env


@pytest.mark.xfail(
    strict=True,
    reason="BUG: routers build Supabase clients at import time (ChatbotAgent/LongTermMemory, users/books SupabaseDB, "
    "conversations SupabaseService) so backend.main cannot even be imported without SUPABASE_URL/SUPABASE_KEY",
)
def test_app_imports_without_supabase_env():
    proc = subprocess.run(
        [sys.executable, "-c", "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; import backend.main"],
        cwd=str(REPO_ROOT),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
