"""
Shared pytest setup for the backend suite.

Everything at module level here runs BEFORE any ``backend.*`` module is imported,
which matters because several modules read configuration (and even build Supabase
clients) at import time. The goal is that a local run and a CI run behave the same:

* a developer's ``.env`` is never loaded (``dotenv.load_dotenv`` becomes a no-op);
* every secret-ish variable is either removed or set to an obviously fake value
  (see ``support/env.py``);
* Supabase points at a TEST-NET address that is never routable, and pytest-socket
  (``--allow-hosts`` in pytest.ini) plus the DNS guard below make any leaked real
  network call fail loudly instead of silently hitting a live service.
"""

from __future__ import annotations

import ipaddress
import socket
import sys

import dotenv
import pytest

from support.env import apply_test_env

# 1) Environment -----------------------------------------------------------------------
dotenv.load_dotenv = lambda *args, **kwargs: False  # type: ignore[assignment]
apply_test_env()

# The OCR grading module prints non-ASCII status glyphs at import time; never let a
# cp1252 Windows console turn that into an import error.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
    except Exception:
        pass


# 2) Network guard (DNS) ---------------------------------------------------------------
# pytest-socket blocks connect() to anything but loopback; this also blocks name
# resolution so e.g. `requests.post("https://api.x.ai/...")` fails immediately
# instead of performing a real DNS query first.
_REAL_GETADDRINFO = socket.getaddrinfo
_LOCAL_NAMES = {None, "", "localhost", b"localhost", "testserver"}


class NetworkBlockedError(RuntimeError):
    """Raised when a test tries to resolve a real hostname."""


def _is_ip_literal(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    if not isinstance(host, str):
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host in _LOCAL_NAMES or _is_ip_literal(host):
        return _REAL_GETADDRINFO(host, *args, **kwargs)
    raise NetworkBlockedError(f"DNS lookup for {host!r} blocked: tests must not use the network")


@pytest.fixture(autouse=True)
def _block_dns(monkeypatch, request):
    if not request.node.get_closest_marker("integration"):
        monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
    yield


# 3) Integration gating ----------------------------------------------------------------
def pytest_collection_modifyitems(config, items):
    import os

    if os.getenv("RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="integration test: set RUN_INTEGRATION=1 (needs live services/keys)")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)


# 4) Shared fixtures -------------------------------------------------------------------
@pytest.fixture(scope="session")
def app():
    """The real FastAPI app. Startup hooks are NOT run (TestClient is used without `with`)."""
    from backend.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def job_manager_factory(tmp_path):
    """Build an OCRJobManager whose job/result files live under tmp_path."""
    from backend.ocr.job_manager import OCRJobManager

    def _make(name: str = "ocr"):
        return OCRJobManager(
            jobs_dir=str(tmp_path / f"{name}_jobs"),
            results_dir=str(tmp_path / f"{name}_results"),
        )

    return _make
