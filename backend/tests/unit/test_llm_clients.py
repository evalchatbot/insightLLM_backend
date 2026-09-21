"""
HTTP boundaries of the three LLM clients:
  * backend.utils.grok_client      (requests)  -- Fact Book + evaluation pipeline
  * backend.ocr.grok_client        (requests)  -- retrying/repairing Grok caller for grading
  * backend.rag.llm.streaming_client (httpx)   -- Groq SSE streaming for the chatbot
No request leaves the process: requests.post is replaced and httpx gets a MockTransport.
"""

from __future__ import annotations

import json
import types

import httpx
import pytest
import requests

from backend.ocr import grok_client as ocr_grok
from backend.rag.llm import streaming_client as sc
from backend.utils import grok_client as ug
from support.fakes import RecordingPost, grok_completion, make_requests_response

pytestmark = pytest.mark.unit

# ====================================================================== utils.grok_client


def test_client_requires_key(monkeypatch):
    with pytest.raises(RuntimeError, match="Missing Grok API key"):
        ug.GrokClient()


def test_client_reads_key_and_base_url_from_env(monkeypatch):
    monkeypatch.setenv("GROK_API", "env-key")
    monkeypatch.setenv("GROK_API_BASE_URL", "https://grok.internal/v2/")
    client = ug.GrokClient(timeout=7)
    assert client.api_key == "env-key"
    assert client.timeout == 7
    post = RecordingPost(make_requests_response(200, grok_completion("hi")))
    monkeypatch.setattr(ug.requests, "post", post)
    client.chat_completion(model="m", messages=[ug.GrokMessage("user", "q")])
    assert post.calls[0]["url"] == "https://grok.internal/v2/chat/completions"
    assert post.calls[0]["timeout"] == 7


def test_chat_completion_payload_and_usage(monkeypatch):
    post = RecordingPost(
        make_requests_response(200, grok_completion("answer", usage={"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15}))
    )
    monkeypatch.setattr(ug.requests, "post", post)
    client = ug.GrokClient(api_key="k")
    data = client.chat_completion(
        model="grok-x",
        messages=[ug.GrokMessage("system", "s"), ug.GrokMessage("user", [{"type": "text", "text": "q"}])],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_output_tokens=500,
    )
    sent = json.loads(post.calls[0]["data"])
    assert sent == {
        "model": "grok-x",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": [{"type": "text", "text": "q"}]}],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "max_output_tokens": 500,
    }
    assert post.calls[0]["headers"]["Authorization"] == "Bearer k"
    assert data["_token_usage"] == {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15}
    assert ug.extract_content_text(data) == "answer"


def test_chat_completion_omits_optional_fields(monkeypatch):
    post = RecordingPost(make_requests_response(200, grok_completion("x")))
    monkeypatch.setattr(ug.requests, "post", post)
    data = ug.GrokClient(api_key="k").chat_completion(model="m", messages=[])
    sent = json.loads(post.calls[0]["data"])
    assert "response_format" not in sent and "max_output_tokens" not in sent
    assert "_token_usage" not in data


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (make_requests_response(401, {"error": "invalid key"}), "Grok API error 401: {'error': 'invalid key'}"),
        (make_requests_response(502, text="<html>Bad gateway</html>"), "Grok API error 502: <html>Bad gateway</html>"),
        (make_requests_response(200, text="not json"), "Invalid JSON in Grok response"),
    ],
)
def test_chat_completion_errors(monkeypatch, response, match):
    monkeypatch.setattr(ug.requests, "post", RecordingPost(response))
    with pytest.raises(ug.GrokError, match=match):
        ug.GrokClient(api_key="k").chat_completion(model="m", messages=[])


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"choices": [{"message": {"content": "x"}}]}, "x"),
        ({"choices": [{"message": {"content": None}}]}, ""),
    ],
)
def test_extract_content_text(payload, expected):
    assert ug.extract_content_text(payload) == expected


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{}]}, {"choices": "nope"}])
def test_extract_content_text_malformed(payload):
    with pytest.raises(ug.GrokError, match="Malformed Grok response"):
        ug.extract_content_text(payload)


# ====================================================================== ocr.grok_client


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('Here is the result:\n{"a": {"b": 1}}\nThanks', '{"a": {"b": 1}}'),
        ("no json", "no json"),
    ],
)
def test_clean_json_from_llm(raw, expected):
    assert ocr_grok._clean_json_from_llm(raw) == expected


def test_repair_json_trailing_commas_and_control_chars():
    broken = '{"a": [1, 2,], "b": "x\x07y",\n}'
    assert json.loads(ocr_grok._repair_json(broken)) == {"a": [1, 2], "b": "xy"}


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(ocr_grok.time, "sleep", lambda s: slept.append(s))
    return slept


def ok(content, finish="stop", usage=None):
    return make_requests_response(200, grok_completion(content, finish_reason=finish, usage=usage or {"prompt_tokens": 10, "completion_tokens": 5}))


def test_call_grok_api_success(monkeypatch):
    post = RecordingPost(ok('```json\n{"score": 12}\n```'))
    monkeypatch.setattr(ocr_grok.requests, "post", post)
    parsed, usage = ocr_grok.call_grok_api("key", {"model": "m", "messages": []})
    assert parsed == {"score": 12}
    assert usage == {"input_tokens": 10, "output_tokens": 5}
    assert post.calls[0]["url"] == ocr_grok.GROK_CHAT_URL
    assert post.calls[0]["headers"]["Authorization"] == "Bearer key"
    assert post.calls[0]["json"] == {"model": "m", "messages": []}


def test_call_grok_api_retries_http_and_network_errors(monkeypatch, no_sleep):
    post = RecordingPost(make_requests_response(503, text="busy"), requests.ConnectionError("reset"), ok('{"ok": true}'))
    monkeypatch.setattr(ocr_grok.requests, "post", post)
    parsed, _ = ocr_grok.call_grok_api("k", {}, retry_backoff=True)
    assert parsed == {"ok": True}
    assert len(post.calls) == 3
    assert no_sleep == [1, 2]  # exponential backoff between attempts


def test_call_grok_api_gives_up(monkeypatch):
    monkeypatch.setattr(ocr_grok.requests, "post", RecordingPost(*[make_requests_response(500, text="err")] * 2))
    with pytest.raises(ocr_grok.GrokAPIError, match="Grok API error 500"):
        ocr_grok.call_grok_api("k", {}, max_retries=2)


def test_call_grok_api_network_failure(monkeypatch):
    monkeypatch.setattr(ocr_grok.requests, "post", RecordingPost(requests.Timeout("slow")))
    with pytest.raises(ocr_grok.GrokAPIError, match="network error"):
        ocr_grok.call_grok_api("k", {}, max_retries=1)


def test_call_grok_api_truncation_raises_budget_then_succeeds(monkeypatch):
    post = RecordingPost(ok('{"partial": ', finish="length"), ok('{"done": 1}'))
    monkeypatch.setattr(ocr_grok.requests, "post", post)
    payload = {"max_tokens": 4000}
    parsed, _ = ocr_grok.call_grok_api("k", payload)
    assert parsed == {"done": 1}
    assert payload["max_tokens"] == 6000


def test_call_grok_api_truncated_on_last_attempt(monkeypatch):
    monkeypatch.setattr(ocr_grok.requests, "post", RecordingPost(ok('{"x": ', finish="length")))
    with pytest.raises(ocr_grok.GrokAPIError) as err:
        ocr_grok.call_grok_api("k", {}, max_retries=1)
    assert err.value.raw_content == '{"x": '
    assert err.value.token_usage == {"input_tokens": 10, "output_tokens": 5}


def test_call_grok_api_repairs_trailing_commas(monkeypatch):
    monkeypatch.setattr(ocr_grok.requests, "post", RecordingPost(ok('{"items": [1, 2,],}')))
    parsed, _ = ocr_grok.call_grok_api("k", {})
    assert parsed == {"items": [1, 2]}


def test_call_grok_api_unrepairable_json_dumps_debug_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr_grok.requests, "post", RecordingPost(ok("{'single': 'quotes'}"), ok("{still broken")))
    with pytest.raises(ocr_grok.GrokAPIError, match="malformed JSON after 2 attempts") as err:
        ocr_grok.call_grok_api("k", {}, max_retries=2, error_file_prefix=str(tmp_path / "grok_err"))
    assert err.value.raw_content == "{still broken"
    dumps = sorted(p.name for p in tmp_path.iterdir())
    assert len(dumps) == 2 and all(n.startswith("grok_err_") for n in dumps)


def test_call_grok_api_without_repair_retries_parse_errors(monkeypatch):
    post = RecordingPost(ok('{"a": 1,}'), ok('{"a": 2}'))
    monkeypatch.setattr(ocr_grok.requests, "post", post)
    parsed, _ = ocr_grok.call_grok_api("k", {}, use_repair=False)
    assert parsed == {"a": 2}


def test_call_grok_api_unexpected_structure(monkeypatch):
    monkeypatch.setattr(ocr_grok.requests, "post", RecordingPost(make_requests_response(200, {"id": "x", "usage": {}})))
    with pytest.raises(ocr_grok.GrokAPIError, match="Unexpected Grok API response structure"):
        ocr_grok.call_grok_api("k", {}, max_retries=1)


# ====================================================================== streaming client (httpx)


def sse(*events, done=True):
    lines = [f"data: {json.dumps(e)}" if not isinstance(e, str) else e for e in events]
    if done:
        lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def delta(text):
    return {"choices": [{"delta": {"content": text}}]}


@pytest.fixture
def transport(monkeypatch):
    """Route the streaming client's httpx.AsyncClient through a MockTransport."""
    state = {"requests": [], "response": httpx.Response(200)}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["response"]

    mock = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = mock
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(sc, "httpx", types.SimpleNamespace(AsyncClient=_Client))
    monkeypatch.setattr(sc, "get_token_count", lambda text, model="gpt-4": len(text.split()))
    return state


async def collect(gen):
    return [item async for item in gen]


async def test_stream_parses_deltas_usage_and_skips_noise(transport):
    transport["response"] = httpx.Response(
        200,
        content=sse(delta("Hello"), "data: {not json", delta(""), {"choices": []}, delta(" world"),
                    {"usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}}),
        headers={"content-type": "text/event-stream"},
    )
    client = sc.StreamingLLMClient("groq-key", "llama-test")
    items = await collect(client.generate_stream("Q?", temperature=0.2, max_tokens=64, system_message="SYS"))
    assert items == [("Hello", None), (" world", None), (None, {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14})]

    (req,) = transport["requests"]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer groq-key"
    body = json.loads(req.content)
    assert body["stream"] is True
    assert body["model"] == "llama-test"
    assert body["max_tokens"] == 64 and body["temperature"] == 0.2
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Q?"}]


async def test_stream_without_provider_usage_reports_prompt_estimate(transport):
    transport["response"] = httpx.Response(200, content=sse(delta("a")))
    items = await collect(sc.StreamingLLMClient("k", "m").generate_stream("one two three", system_message="sys"))
    assert items[-1] == (None, {"prompt_tokens": 4, "completion_tokens": 0, "total_tokens": 4})


async def test_stream_http_error_becomes_inline_error_chunk(transport):
    transport["response"] = httpx.Response(429, json={"error": "rate limited"})
    items = await collect(sc.StreamingLLMClient("k", "m").generate_stream("q"))
    assert len(items) == 1
    chunk, usage = items[0]
    assert chunk.startswith("[Streaming Error:") and "429" in chunk
    assert usage is None


async def test_generate_complete_joins_and_counts_tokens(transport):
    transport["response"] = httpx.Response(200, content=sse(delta("Power "), delta("is shared.")))
    text, usage = await sc.StreamingLLMClient("k", "m").generate_complete("What is federalism?", system_message="S")
    assert text == "Power is shared."
    assert usage == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}


def test_streaming_client_validation():
    with pytest.raises(RuntimeError):
        sc.StreamingLLMClient("", "m")
    with pytest.raises(ValueError, match="Unsupported provider"):
        sc.StreamingLLMClient("k", "m", provider="cohere")
    assert sc.StreamingLLMClient("k", "m", provider="OpenAI").url == "https://api.openai.com/v1/chat/completions"


@pytest.fixture
def fresh_settings():
    from backend.rag.config import get_rag_settings

    get_rag_settings.cache_clear()
    yield
    get_rag_settings.cache_clear()


def test_client_factory_requires_groq_key(fresh_settings):
    with pytest.raises(RuntimeError, match="GROQ_API_KEY not set"):
        sc.get_streaming_llm_client()


def test_client_factory_builds_groq_client(fresh_settings, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setenv("GROQ_MODEL_NAME", "llama-custom")
    client = sc.get_streaming_llm_client()
    assert (client.provider, client.model, client.api_key) == ("groq", "llama-custom", "gk")


@pytest.mark.parametrize(("provider", "message"), [("openai", "OPENAI_API_KEY not set"), ("bedrock", "Unsupported LLM_PROVIDER")])
def test_client_factory_other_providers(fresh_settings, monkeypatch, provider, message):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    with pytest.raises(RuntimeError, match=message):
        sc.get_streaming_llm_client()
