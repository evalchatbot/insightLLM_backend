"""Pure logic inside ChatbotAgent: question sanitising, analysis, prompt building, stream wrapper."""

from __future__ import annotations

import uuid

import pytest

from backend.agents.chatbot_agent import SYSTEM_PROMPT, ChatbotAgent

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def agent():
    return ChatbotAgent()


# ---------------------------------------------------------------- sanitising


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("What is federalism?", "What is federalism?"),
        ("User: hi\nAssistant: hello\nCurrent question:\nDefine judicial review", "Define judicial review"),
        ("Context:\nQuestion:\nExplain the 18th Amendment", "Explain the 18th Amendment"),
        ("hi", "hi"),
        ("", ""),
        (None, None),
    ],
)
def test_sanitize_question(agent, raw, expected):
    assert agent._sanitize_question(raw) == expected


# ---------------------------------------------------------------- analysis


async def test_empty_question_is_brief(agent):
    assert await agent._analyze_question("   ") == {"mode": "brief", "reason": "empty_question"}


@pytest.mark.parametrize("greeting", ["hi", "Hello!", "salam", "thanks a lot"])
async def test_greetings_are_brief(agent, greeting):
    analysis = await agent._analyze_question(greeting)
    assert analysis["mode"] == "brief"
    assert analysis["expected_length"] == "short"


async def test_essay_question_directives_and_reasoning(agent):
    a = await agent._analyze_question("Critically evaluate the impact of the 18th Amendment on federalism.")
    assert a["mode"] == "essay"
    assert "deliver a critical appraisal" in a["directives"]
    assert "evaluate strengths and weaknesses" in a["directives"]
    assert "cause-effect reasoning" in a["reasoning_focus"]
    assert "evaluative judgement" in a["reasoning_focus"]
    assert "federalism" in a["key_terms"]
    assert (a["suggested_subheadings_min"], a["suggested_subheadings_max"]) == (10, 14)


async def test_comparison_pairs_extracted(agent):
    a = await agent._analyze_question("Compare between presidential and parliamentary systems.")
    assert a["comparison_pairs"] == [{"item_a": "PRESIDENTIAL", "item_b": "PARLIAMENTARY SYSTEMS"}]
    assert "comparative reasoning" in a["reasoning_focus"]


async def test_constitutional_democracy_template(agent):
    q = "What are the principles of constitutional democracy and how do they protect minority rights?"
    a = await agent._analyze_question(q)
    assert "rule of law" in a["principles"]
    assert len(a["multi_part_breakdown"]) == 2
    assert {"constitutional democracy", "minority rights"} <= set(a["key_terms"])


async def test_short_statement_without_triggers_is_brief(agent):
    a = await agent._analyze_question("Objectives Resolution 1949")
    assert a["mode"] == "brief"
    assert a["suggested_subheadings_max"] == 0
    assert a["directives"] == ["explain the topic comprehensively with relevant context"]


async def test_long_question_is_essay_even_without_triggers(agent):
    q = " ".join(["word"] * 18)
    assert (await agent._analyze_question(q))["mode"] == "essay"


# ---------------------------------------------------------------- prompt building


async def test_brief_prompt(agent):
    analysis = await agent._analyze_question("hello")
    prompt = agent._build_user_prompt("hello", [], analysis)
    assert prompt.startswith("Question:\n\nhello")
    assert "120–180 words" in prompt
    assert "## Introduction" not in prompt


async def test_essay_prompt_includes_history_structure_and_directives(agent):
    q = "Compare between unitary and federal systems."
    analysis = await agent._analyze_question(q)
    history = [{"sender": "user", "message": f"m{i}"} for i in range(8)] + [{"sender": "assistant", "message": "  "}]
    prompt = agent._build_user_prompt(q, history, analysis)
    assert "Recent exchange (latest last):" in prompt
    assert "User: m7" in prompt and "User: m2" not in prompt  # only the last 6 entries
    assert "Exam Question:\n\nCompare between unitary and federal systems." in prompt
    assert "## Introduction" in prompt and "## Conclusion" in prompt
    assert "## Exam Technique Guidance" in prompt
    assert "contrasting UNITARY and FEDERAL SYSTEMS" in prompt
    assert "Address the following directives explicitly: compare contrasting perspectives" in prompt
    assert "Never mention the acronym 'CSS'." in prompt


def test_system_prompt_forbids_css_acronym():
    assert "Never mention the acronym 'CSS'" in SYSTEM_PROMPT


# ---------------------------------------------------------------- stream wrapper


class ScriptedLLM:
    def __init__(self, items):
        self.items = items

    async def generate_stream(self, prompt, **kwargs):
        for item in self.items:
            yield item

    async def generate_complete(self, prompt, **kwargs):
        return "A Title", {}


class NullLongTerm:
    def save_fact(self, *a, **k):
        pass


async def _drain(agent, llm, monkeypatch):
    monkeypatch.setattr(agent, "_streaming_client", llm)
    monkeypatch.setattr(agent, "long_term", NullLongTerm())
    monkeypatch.setattr(agent, "db_service", None)
    session = f"stream-{uuid.uuid4().hex}"
    stream = await agent.stream_answer(user_id="u", session_id=session, question="Why does inflation persist?")
    chunks = [c async for c in stream]
    return stream, chunks


async def test_stream_wrapper_skips_usage_frames_and_collects_answer(agent, monkeypatch):
    llm = ScriptedLLM([("Prices ", None), (None, None), ("keep rising.", None), (None, {"prompt_tokens": 50, "completion_tokens": 4, "total_tokens": 54})])
    stream, chunks = await _drain(agent, llm, monkeypatch)
    assert chunks == ["Prices ", "keep rising."]
    assert stream.answer == "Prices keep rising."
    assert stream.token_usage == {"prompt_tokens": 50, "completion_tokens": 4, "total_tokens": 54}
    assert stream.update_info["suggested_title"] == "A Title"
    assert stream.analysis["mode"] == "essay"


async def test_stream_wrapper_estimates_completion_tokens_when_provider_omits_them(agent, monkeypatch):
    from backend.utils import usage_tracking

    monkeypatch.setattr(usage_tracking, "get_token_count", lambda text, model="gpt-4": len(text.split()))
    llm = ScriptedLLM([("one two three", None), (None, {"prompt_tokens": 40, "completion_tokens": 0, "total_tokens": 40})])
    stream, _ = await _drain(agent, llm, monkeypatch)
    assert stream.token_usage == {"prompt_tokens": 40, "completion_tokens": 3, "total_tokens": 43}


async def test_stream_wrapper_computes_usage_when_none_reported(agent, monkeypatch):
    from backend.utils import usage_tracking

    monkeypatch.setattr(usage_tracking, "get_token_count", lambda text, model="gpt-4": 7)
    stream, _ = await _drain(agent, ScriptedLLM([("x", None)]), monkeypatch)
    assert stream.token_usage == {"prompt_tokens": 7, "completion_tokens": 7, "total_tokens": 14}


async def test_title_generation_is_cleaned_and_capped(agent, monkeypatch):
    class TitleLLM:
        async def generate_complete(self, prompt, **kwargs):
            return '"' + "Long Title " * 10 + '"\n', {}

    monkeypatch.setattr(agent, "_streaming_client", TitleLLM())
    title = await agent._generate_conversation_title("q", "a" * 1000)
    assert len(title) == 60
    assert not title.startswith('"')


async def test_empty_title_falls_back(agent, monkeypatch):
    class EmptyLLM:
        async def generate_complete(self, prompt, **kwargs):
            return "  \n", {}

    monkeypatch.setattr(agent, "_streaming_client", EmptyLLM())
    assert await agent._generate_conversation_title("q", "a") == "CSS Prep Chat"


async def test_create_conversation_without_db_returns_none(agent, monkeypatch):
    monkeypatch.setattr(agent, "db_service", None)
    assert await agent.create_conversation_with_title("u", "q", "a") is None
