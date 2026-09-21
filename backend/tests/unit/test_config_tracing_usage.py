"""Config/env parsing, LangSmith tracer switch, token usage tracking, short-term memory."""

from __future__ import annotations

import importlib.util
import os
import uuid

import pytest

from support.env import REPO_ROOT
from support.fakes import FakeSupabaseClient

pytestmark = pytest.mark.unit


def fresh_copy(relpath: str):
    """Execute a module's source into a brand-new module object (sys.modules untouched)."""
    name = f"_fresh_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONFIG_VARS = [
    "FACTBOOK_SCHEDULER_ENABLED",
    "FACTBOOK_SCHEDULER_TIMES",
    "FACTBOOK_FETCH_PROXY_PREFIX",
    "FACTBOOK_FETCH_MIN_INTERVAL_SECONDS",
    "FACTBOOK_AUTO_SYNC_TODAY_ON_EMPTY",
    "FACTBOOK_TIMEZONE",
    "FACTBOOK_CATCHUP_DAYS",
    "FACTBOOK_TOPIC_MODEL",
    "FACTBOOK_GROK_MODEL",
    "LANGSMITH_TRACING",
    "OCR_MAX_RETRIES",
    "CHATBOT_LLM_MODEL",
]


@pytest.fixture
def clean_config_env(monkeypatch):
    for var in CONFIG_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ====================================================================== config


def test_config_defaults(clean_config_env):
    cfg = fresh_copy("backend/config.py")
    assert cfg.FACTBOOK_SCHEDULER_ENABLED is True
    assert cfg.FACTBOOK_SCHEDULER_TIMES == "08:30"
    assert cfg.FACTBOOK_TIMEZONE == "Asia/Karachi"
    assert cfg.FACTBOOK_CATCHUP_DAYS == 0
    assert cfg.FACTBOOK_FETCH_PROXY_PREFIX == "https://r.jina.ai/"
    assert cfg.FACTBOOK_FETCH_MIN_INTERVAL_SECONDS == 3.2
    assert cfg.FACTBOOK_AUTO_SYNC_TODAY_ON_EMPTY is True
    assert cfg.FACTBOOK_TOPIC_MODEL == cfg.FACTBOOK_GROK_MODEL == "grok-4-1-fast-reasoning"
    assert cfg.GROK_API_BASE_URL == "https://api.x.ai/v1"
    assert cfg.SUPABASE_ISSUER == "/auth/v1"
    assert cfg.SUPABASE_AUDIENCE == "authenticated"
    assert cfg.LANGSMITH_TRACING == "false"
    assert cfg.OCR_MAX_RETRIES == 3
    assert cfg.CHATBOT_LLM_MODEL == "llama-3.1-8b-instant"


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("TRUE", True), ("false", False), ("1", False), ("yes", False)])
def test_boolean_flags_only_accept_true(clean_config_env, raw, expected):
    clean_config_env.setenv("FACTBOOK_SCHEDULER_ENABLED", raw)
    assert fresh_copy("backend/config.py").FACTBOOK_SCHEDULER_ENABLED is expected


def test_empty_values_fall_back_or_disable(clean_config_env):
    clean_config_env.setenv("FACTBOOK_FETCH_MIN_INTERVAL_SECONDS", "")
    clean_config_env.setenv("FACTBOOK_FETCH_PROXY_PREFIX", "   ")
    cfg = fresh_copy("backend/config.py")
    assert cfg.FACTBOOK_FETCH_MIN_INTERVAL_SECONDS == 3.2
    assert cfg.FACTBOOK_FETCH_PROXY_PREFIX == ""  # direct fetch


def test_topic_model_follows_grok_model(clean_config_env):
    clean_config_env.setenv("FACTBOOK_GROK_MODEL", "grok-5")
    assert fresh_copy("backend/config.py").FACTBOOK_TOPIC_MODEL == "grok-5"


def test_grok_key_accepts_legacy_mixed_case_name(clean_config_env):
    clean_config_env.setenv("Grok_API", "legacy-key")
    assert fresh_copy("backend/config.py").GROK_API == "legacy-key"


def test_suite_runs_with_scheduler_disabled_and_fake_supabase():
    from backend import config

    assert config.FACTBOOK_SCHEDULER_ENABLED is False
    assert config.SUPABASE_URL.startswith("http://192.0.2.")
    assert config.GROK_API is None


# ====================================================================== LangSmith tracer


class FakeLangSmithClient:
    instances = []

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.runs = []
        FakeLangSmithClient.instances.append(self)

    def create_run(self, **kwargs):
        self.runs.append(kwargs)


@pytest.fixture
def tracer_env(monkeypatch):
    """Load fresh config+tracer copies under a given env; restore os.environ afterwards."""
    import langsmith

    from backend import config

    monkeypatch.setattr(langsmith, "Client", FakeLangSmithClient)
    saved = dict(os.environ)

    def load(tracing: str, api_key: str | None):
        monkeypatch.setenv("LANGSMITH_TRACING", tracing)
        if api_key:
            monkeypatch.setenv("LANGSMITH_API_KEY", api_key)
        cfg = fresh_copy("backend/config.py")
        monkeypatch.setattr(config, "LANGSMITH_TRACING", cfg.LANGSMITH_TRACING)
        monkeypatch.setattr(config, "LANGSMITH_API_KEY", cfg.LANGSMITH_API_KEY)
        return fresh_copy("backend/rag/telemetry/langsmith_tracer.py")

    yield load
    for key in set(os.environ) - set(saved):
        del os.environ[key]
    os.environ.update(saved)


def test_tracer_disabled_without_key(tracer_env):
    tracer = tracer_env("true", None)
    assert tracer.LangSmithTracer.is_enabled() is False

    def f():
        return 1

    assert tracer.trace_agent_method()(f) is f
    assert tracer.trace_llm_call()(f) is f
    assert tracer.trace_retrieval()(f) is f
    tracer.log_to_langsmith("run", {}, {})  # no-op, no error


def test_tracer_enabled_with_true_and_key(tracer_env):
    tracer = tracer_env("true", "ls-key")
    assert tracer.LangSmithTracer.is_enabled() is True
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    tracer.log_to_langsmith("run", {"q": 1}, {"a": 2}, tags=["x"])
    assert tracer.langsmith_client.runs[0]["tags"] == ["x", "insightLLM"]


@pytest.mark.xfail(
    strict=True,
    reason="BUG: config.LANGSMITH_TRACING is the raw lowercase string, and langsmith_tracer tests it for "
    "truthiness, so LANGSMITH_TRACING=false still enables tracing whenever LANGSMITH_API_KEY is set",
)
def test_tracer_respects_tracing_false(tracer_env):
    tracer = tracer_env("false", "ls-key")
    assert tracer.LangSmithTracer.is_enabled() is False


async def test_trace_run_is_a_noop_context_when_disabled(tracer_env):
    tracer = tracer_env("false", None)
    async with tracer.LangSmithTracer.trace_run("x") as run:
        assert run is None
    with tracer.LangSmithTracer.trace_sync("x") as run:
        assert run is None


# ====================================================================== usage tracking


def test_token_count_uses_tiktoken_when_available(monkeypatch):
    from backend.utils import usage_tracking as ut

    class Enc:
        def encode(self, text):
            return text.split()

    monkeypatch.setattr(ut.tiktoken, "encoding_for_model", lambda model: Enc())
    assert ut.get_token_count("one two three") == 3


def test_token_count_falls_back_to_chars_over_four(monkeypatch):
    from backend.utils import usage_tracking as ut

    def offline(model):
        raise OSError("cannot download BPE")

    monkeypatch.setattr(ut.tiktoken, "encoding_for_model", offline)
    assert ut.get_token_count("x" * 41) == 10
    assert ut.get_token_count("") == 0


@pytest.fixture
def usage_db(monkeypatch):
    from backend.utils import usage_tracking as ut

    fake = FakeSupabaseClient(rpc_results={"record_usage": [{"tokens_input": 120}]})
    created = []

    def fake_create_client(url, key):
        created.append((url, key))
        return fake

    monkeypatch.setattr(ut, "create_client", fake_create_client)
    return fake, created


async def test_record_usage_calls_rpc(usage_db):
    from backend.utils.usage_tracking import record_usage

    fake, created = usage_db
    result = await record_usage("7d88e562-35ed-465c-82ac-921a34412b49", input_tokens=120, output_tokens=30)
    assert result == [{"tokens_input": 120}]
    assert fake.rpc_calls == [
        ("record_usage", {"p_user_id": "7d88e562-35ed-465c-82ac-921a34412b49", "p_input_tokens": 120, "p_output_tokens": 30})
    ]
    assert created and created[0][0].startswith("http://192.0.2.")


async def test_record_usage_returns_none_on_empty_or_error(usage_db):
    from backend.utils.usage_tracking import record_usage

    fake, _ = usage_db
    fake.rpc_results["record_usage"] = []
    assert await record_usage("user-1") is None
    fake.rpc_results["record_usage"] = RuntimeError("function record_usage does not exist")
    assert await record_usage("user-1") is None


# ====================================================================== short-term memory


def test_short_term_memory_is_per_session():
    from backend.memory.short_term import ShortTermMemory

    mem = ShortTermMemory(summarization_threshold=2)
    mem.add_message("u", "s1", {"sender": "user", "message": "hi"})
    mem.add_message("u", "s2", {"sender": "user", "message": "other session"})
    assert mem.get_recent_messages("u", "s1") == [{"sender": "user", "message": "hi"}]
    assert mem.should_summarize("u", "s1") is False
    mem.add_message("u", "s1", {"sender": "assistant", "message": "hello"})
    assert [m["message"] for m in mem.get_recent_messages("u", "s1")] == ["hi", "hello"]
    assert mem.should_summarize("u", "s1") is True
    mem.reset_conversation_count("u", "s1")
    assert mem.get_conversation_count("u", "s1") == 0
    mem.clear("u", "s1")
    assert mem.get_recent_messages("u", "s1") == []
    assert mem.get_conversation_count("u", "s2") == 1

