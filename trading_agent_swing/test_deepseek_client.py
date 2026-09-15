"""
DeepSeek adapter tests — message conversion and response parsing. No network.
The critical case is tool_call_id injection: agent.py emits bare
{"role": "tool"} messages (fine for Ollama/Gemini) but the OpenAI wire format
requires an id, so the client must pair results to calls in order.
Run: python -m pytest test_deepseek_client.py
"""
import json

import pytest

from deepseek_client import DeepSeekClient


def _client():
    return DeepSeekClient(api_key="test-key-not-real")


# ── construction ─────────────────────────────────────────────────────────────

def test_rejects_missing_key():
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        DeepSeekClient(api_key="")


def test_rejects_placeholder_key():
    with pytest.raises(RuntimeError):
        DeepSeekClient(api_key="PASTE_YOUR_KEY_HERE")


# ── retry policy ─────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code, text="err"):
        self.status_code, self.text = status_code, text

    def json(self):
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    def raise_for_status(self):
        pass


def _client_with_responses(monkeypatch, statuses):
    """Client whose POST returns the given statuses in order; counts calls."""
    c = _client()
    calls = {"n": 0}
    seq = list(statuses)

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(seq[min(calls["n"] - 1, len(seq) - 1)])

    monkeypatch.setattr(c._session, "post", fake_post)
    monkeypatch.setattr("deepseek_client.time.sleep", lambda s: None)
    return c, calls


def test_unfunded_account_fails_immediately(monkeypatch):
    """402 is permanent — retrying an unfunded account 5 times just wastes
    75 seconds and reports a raw status code instead of the actual problem."""
    c, calls = _client_with_responses(monkeypatch, [402])
    with pytest.raises(RuntimeError, match="out of credit"):
        c.chat(model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}])
    assert calls["n"] == 1, "must not retry a permanent failure"


def test_bad_key_fails_immediately_with_a_usable_message(monkeypatch):
    c, calls = _client_with_responses(monkeypatch, [401])
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        c.chat(model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}])
    assert calls["n"] == 1


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    """429 and 5xx ARE transient — these must still retry."""
    c, calls = _client_with_responses(monkeypatch, [429, 503, 200])
    out = c.chat(model="deepseek-v4-flash", messages=[{"role": "user", "content": "hi"}])
    assert out["message"]["content"] == "ok"
    assert calls["n"] == 3


# ── message conversion ───────────────────────────────────────────────────────

def test_tool_result_gets_id_from_preceding_call():
    """The bug this guards: a bare tool message would be rejected by the API."""
    messages = [
        {"role": "system", "content": "you are a scout"},
        {"role": "user", "content": "pick one"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "get_bars", "arguments": {"symbol": "SPY"}}},
        ]},
        {"role": "tool", "content": '{"result": []}'},
    ]
    out = DeepSeekClient._convert_messages(messages)
    assistant = next(m for m in out if m["role"] == "assistant")
    tool = next(m for m in out if m["role"] == "tool")
    assert tool["tool_call_id"] == assistant["tool_calls"][0]["id"]


def test_multiple_tool_results_pair_in_order():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "get_quote", "arguments": {"symbol": "SPY"}}},
            {"function": {"name": "get_quote", "arguments": {"symbol": "JNJ"}}},
        ]},
        {"role": "tool", "content": "first"},
        {"role": "tool", "content": "second"},
    ]
    out = DeepSeekClient._convert_messages(messages)
    ids = [tc["id"] for tc in out[0]["tool_calls"]]
    tools = [m for m in out if m["role"] == "tool"]
    assert [t["tool_call_id"] for t in tools] == ids


def test_existing_tool_call_id_is_respected():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_abc", "function": {"name": "get_quote", "arguments": {}}},
        ]},
        {"role": "tool", "content": "x", "tool_call_id": "call_abc"},
    ]
    out = DeepSeekClient._convert_messages(messages)
    assert out[1]["tool_call_id"] == "call_abc"


def test_dict_arguments_serialized_to_json_string():
    """OpenAI wire format wants arguments as a string, not an object."""
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "propose_trade",
                          "arguments": {"symbol": "SPY", "qty": 3}}},
        ]},
    ]
    out = DeepSeekClient._convert_messages(messages)
    args = out[0]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(args, str)
    assert json.loads(args)["symbol"] == "SPY"


def test_plain_messages_pass_through():
    out = DeepSeekClient._convert_messages([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ])
    assert [m["role"] for m in out] == ["system", "user"]


# ── response conversion ──────────────────────────────────────────────────────

def test_response_with_tool_calls_matches_agent_expectations():
    """agent.py reads tc['function']['name'] and json.loads() the arguments."""
    data = {"choices": [{"message": {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": "select_candidate",
            "arguments": '{"symbol": "XLI", "rationale": "oversold"}'}}],
    }}]}
    msg = DeepSeekClient._convert_response(data)
    tc = msg["tool_calls"][0]
    assert tc["function"]["name"] == "select_candidate"
    assert json.loads(tc["function"]["arguments"])["symbol"] == "XLI"


def test_plain_text_response():
    data = {"choices": [{"message": {"role": "assistant",
                                     "content": "NO PICK THIS CYCLE"}}]}
    msg = DeepSeekClient._convert_response(data)
    assert msg["content"] == "NO PICK THIS CYCLE"
    assert msg["tool_calls"] == []


def test_empty_choices_does_not_crash():
    msg = DeepSeekClient._convert_response({"choices": []})
    assert msg["role"] == "assistant" and msg["tool_calls"] == []


def test_null_content_becomes_empty_string():
    """A tool-call-only turn returns content=None; agent.py would print 'None'."""
    data = {"choices": [{"message": {"role": "assistant", "content": None,
                                     "tool_calls": []}}]}
    assert DeepSeekClient._convert_response(data)["content"] == ""
