"""
DeepSeek adapter (Exp5 Arm B).

Lets the bot run on DeepSeek's OpenAI-compatible chat-completions API anywhere
it would otherwise use Ollama or Gemini. DeepSeekClient.chat() deliberately
mimics the Ollama client's interface — same inputs (model, messages, tools),
same return shape ({"message": {role, content, tool_calls}}) — so the
three-stage agent loop does not need to know which model is behind it.

Switching is done entirely in .env via MODEL_PROVIDER; no code path changes.

Why raw `requests` instead of the openai SDK: requests is already a transitive
dependency (alpaca-py), the chat-completions contract is small, and the droplet
has 512MB of RAM — no reason to add a package for one POST.

ONE REAL INCOMPATIBILITY, handled here: agent.py appends tool results as bare
{"role": "tool", "content": ...} messages, which is what Ollama and Gemini
accept. The OpenAI wire format REQUIRES a tool_call_id on every tool message.
Rather than change agent.py (shared by all three providers), this client pairs
each tool result with the preceding assistant message's tool_calls, in order,
and injects the ids on the way out.
"""
import json
import time

import requests

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
REQUEST_TIMEOUT = (30, 90)   # (connect, read) — read is generous: reasoning models stream slowly


class DeepSeekClient:
    """A drop-in stand-in for ollama.Client, exposing the same .chat() method."""

    MAX_RETRIES = 5
    RETRY_WAIT_SECONDS = 15   # DeepSeek throttles under peak load; back off and retry

    def __init__(self, api_key: str, base_url: str = DEEPSEEK_BASE_URL):
        if not api_key or api_key.startswith("PASTE_"):
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Add your key from platform.deepseek.com "
                "to the .env file (and set MODEL_PROVIDER=deepseek)."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    # ── public: mimics ollama.Client.chat() ──
    def chat(self, model: str, messages: list, tools: list = None) -> dict:
        payload = {"model": model, "messages": self._convert_messages(messages)}
        if tools:
            payload["tools"] = tools          # already OpenAI function-schema shape
            payload["tool_choice"] = "auto"

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                r = self._session.post(f"{self._base_url}/chat/completions",
                                       json=payload, timeout=REQUEST_TIMEOUT)
                # 429 = rate limit, 5xx = capacity/outage. Both are worth retrying;
                # DeepSeek's direct API is known to throttle at peak hours.
                if r.status_code == 429 or r.status_code >= 500:
                    last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                    time.sleep(self.RETRY_WAIT_SECONDS)
                    continue
                r.raise_for_status()
                return {"message": self._convert_response(r.json())}
            except requests.exceptions.RequestException as e:
                # Timeouts and connection resets: retry, then give up so the
                # cycle fails cleanly and main.py picks it up next hour.
                last_error = str(e)
                if attempt == self.MAX_RETRIES - 1:
                    break
                time.sleep(self.RETRY_WAIT_SECONDS)

        raise RuntimeError(f"DeepSeek request failed after {self.MAX_RETRIES} attempts: {last_error}")

    # ── message conversion (the tool_call_id fix lives here) ──
    @staticmethod
    def _convert_messages(messages: list) -> list:
        out = []
        pending_ids = []          # tool_call ids from the most recent assistant turn
        for m in messages:
            role = m.get("role")

            if role == "tool":
                # Attach the id this result answers. agent.py appends tool results
                # in the same order as the tool_calls, so pop from the front.
                msg = {"role": "tool", "content": m.get("content", "")}
                if m.get("tool_call_id"):
                    msg["tool_call_id"] = m["tool_call_id"]
                elif pending_ids:
                    msg["tool_call_id"] = pending_ids.pop(0)
                out.append(msg)
                continue

            if role == "assistant":
                msg = {"role": "assistant", "content": m.get("content") or ""}
                tool_calls = m.get("tool_calls") or []
                if tool_calls:
                    normalized = []
                    pending_ids = []
                    for i, tc in enumerate(tool_calls):
                        tc_id = tc.get("id") or f"call_{i}"
                        pending_ids.append(tc_id)
                        fn = tc.get("function", {})
                        args = fn.get("arguments", {})
                        normalized.append({
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": fn.get("name"),
                                # OpenAI wire format wants arguments as a JSON string
                                "arguments": args if isinstance(args, str) else json.dumps(args),
                            },
                        })
                    msg["tool_calls"] = normalized
                out.append(msg)
                continue

            out.append({"role": role, "content": m.get("content", "")})
        return out

    # ── response conversion: OpenAI shape -> the shape agent.py expects ──
    @staticmethod
    def _convert_response(data: dict) -> dict:
        choices = data.get("choices") or []
        if not choices:
            return {"role": "assistant", "content": "(empty response)", "tool_calls": []}
        msg = choices[0].get("message") or {}

        tool_calls = []
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            tool_calls.append({
                "id": tc.get("id"),
                "function": {
                    "name": fn.get("name"),
                    # agent.py json.loads() a string arg itself, so pass it through
                    "arguments": fn.get("arguments", "{}"),
                },
            })

        return {
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
        }
