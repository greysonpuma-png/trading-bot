"""
Gemini adapter.

Lets the bot use Google's Gemini (via the google-genai SDK) anywhere it would
otherwise use local Ollama. GeminiClient.chat() deliberately mimics the Ollama
client's interface — same inputs (model, messages, tools), same return shape
({"message": {role, content, tool_calls}}) — so the three-stage agent loop does
not need to know or care which model is behind it.

Switching is done entirely in .env via MODEL_PROVIDER; no code path changes.
"""
import json
import time

from google import genai
from google.genai import types
from google.genai import errors as genai_errors


class GeminiClient:
    """A drop-in stand-in for ollama.Client, exposing the same .chat() method."""

    MAX_RETRIES = 6          # retry attempts on a rate-limit (HTTP 429)
    RETRY_WAIT_SECONDS = 20  # pause between retries — clears a per-minute quota window

    def __init__(self, api_key: str):
        if not api_key or api_key.startswith("PASTE_"):
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add your Google AI Studio key to the .env file "
                "(and set MODEL_PROVIDER=gemini)."
            )
        # 60s request timeout so a stalled socket raises an exception
        # instead of blocking generate_content() forever. The agent loop's
        # except-clause in main.py then logs and retries on the next cycle.
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=60_000),
        )

    # ── public: mimics ollama.Client.chat() ──
    def chat(self, model: str, messages: list, tools: list = None) -> dict:
        system_instruction, contents = self._convert_messages(messages)

        cfg = {}
        if system_instruction:
            cfg["system_instruction"] = system_instruction
        if tools:
            cfg["tools"] = self._convert_tools(tools)
        config = types.GenerateContentConfig(**cfg) if cfg else None

        # Retry on rate-limit (HTTP 429). The free Gemini tier allows only a few
        # requests per minute; on a 429 we wait out the quota window and retry,
        # so a burst of tool calls degrades to "slow" instead of crashing.
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.models.generate_content(
                    model=model, contents=contents, config=config,
                )
                return {"message": self._convert_response(response)}
            except genai_errors.ClientError as e:
                is_rate_limit = getattr(e, "code", None) == 429 or "429" in str(e)
                if is_rate_limit and attempt < self.MAX_RETRIES - 1:
                    print(f"  [Gemini rate-limited — waiting {self.RETRY_WAIT_SECONDS}s, "
                          f"retry {attempt + 1}/{self.MAX_RETRIES - 1}]")
                    time.sleep(self.RETRY_WAIT_SECONDS)
                    continue
                raise
        raise RuntimeError("Gemini: exhausted retries while rate-limited")

    # ── messages: Ollama format -> Gemini contents ──
    @staticmethod
    def _convert_messages(messages):
        """Returns (system_instruction, contents). The agent loop's message list
        mixes system/user/assistant/tool roles; Gemini wants a system_instruction
        plus an alternating list of user/model Content objects, with tool results
        carried as function_response parts."""
        system_instruction = None
        contents = []
        pending = []  # function-call names from the most recent assistant turn, in order

        for m in messages:
            role = m.get("role")

            if role == "system":
                if system_instruction is None:
                    system_instruction = m.get("content") or ""
                continue

            if role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=m.get("content") or "")],
                ))

            elif role == "assistant":
                parts = []
                if m.get("content"):
                    parts.append(types.Part.from_text(text=m["content"]))
                pending = []
                for tc in (m.get("tool_calls") or []):
                    fn = tc["function"]["name"]
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    parts.append(types.Part.from_function_call(name=fn, args=args or {}))
                    pending.append(fn)
                if not parts:
                    parts.append(types.Part.from_text(text=" "))
                contents.append(types.Content(role="model", parts=parts))

            elif role == "tool":
                # A tool result. The agent's tool message carries no function name,
                # so pair it with the next un-answered call from the assistant turn.
                fn = pending.pop(0) if pending else "tool"
                raw = m.get("content")
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    payload = {"result": raw}
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(name=fn, response=payload)],
                ))

        return system_instruction, contents

    # ── tools: Ollama/OpenAI schema -> Gemini Tool ──
    @staticmethod
    def _convert_tools(tools):
        decls = []
        for t in tools:
            f = t.get("function", {})
            params = f.get("parameters") or {}
            props = params.get("properties") or {}
            kwargs = {
                "name": f.get("name", ""),
                "description": f.get("description", ""),
            }
            # Only attach a parameter schema for tools that actually take arguments.
            if props:
                kwargs["parameters_json_schema"] = params
            decls.append(types.FunctionDeclaration(**kwargs))
        return [types.Tool(function_declarations=decls)]

    # ── response: Gemini -> Ollama-shaped message ──
    @staticmethod
    def _convert_response(response):
        text_out = ""
        tool_calls = []
        for cand in (getattr(response, "candidates", None) or []):
            content = getattr(cand, "content", None)
            for part in (getattr(content, "parts", None) or []):
                if getattr(part, "text", None):
                    text_out += part.text
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    args = getattr(fc, "args", None)
                    args = dict(args) if args else {}
                    tool_calls.append({"function": {"name": fc.name, "arguments": args}})
            break  # only the first candidate
        return {"role": "assistant", "content": text_out, "tool_calls": tool_calls}
