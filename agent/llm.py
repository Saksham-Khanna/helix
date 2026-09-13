"""
Thin wrapper around LLM APIs.

Supports three providers:
  1. Gemini (free tier, no credit card) via google.genai
  2. Groq (free API) via OpenAI-compatible chat completions
  3. Ollama (local) via http://localhost:11434/api/chat

Swap providers by setting MODEL_PROVIDER in .env ("gemini", "groq" or "ollama").
This is the only file that needs to change when swapping providers.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Generator

import httpx

from google import genai
from google.genai import types

from agent.config import get_config
from agent.ratelimit import with_retries, with_retries_stream

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

def _get_gemini_model() -> str:
    return get_config().gemini_model

def _get_groq_model() -> str:
    return get_config().groq_model

def _get_ollama_model() -> str:
    return get_config().ollama_model

def _get_ollama_host() -> str:
    return get_config().ollama_host.rstrip("/")

def _ollama_url() -> str:
    return f"{_get_ollama_host()}/api/chat"

# Keep for backward compat – now dynamic
_config = get_config()
GEMINI_MODEL = _config.gemini_model
GROQ_MODEL = _config.groq_model
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def _groq_request(messages: list, tools: list[dict], system: str, stream: bool = False) -> dict:
    """Low-level Groq call using urllib (no extra dependency needed)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set (if MODEL_PROVIDER=groq). Get free key at https://console.groq.com"
        )

    payload = {
        "model": _get_groq_model(),
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages

    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # urllib ka default Python-urllib User-Agent Cloudflare block karta hai.
            # Browser-like User-Agent lagane se request pass ho jaati hai.
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        def _do_request():
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return with_retries(_do_request)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        if e.code == 403:
            raise RuntimeError(
                "Groq API key rejected (403). Check that GROQ_API_KEY is "
                "valid/active and not revoked. Create a new key at "
                "https://console.groq.com/keys"
            )
        raise RuntimeError(f"Groq API error {e.code}: {body}")


def _groq_stream(messages: list, tools: list[dict], system: str) -> Generator[dict, None, None]:
    """Yield SSE chunks from Groq streaming API (retries only the connection)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    payload = {
        "model": _get_groq_model(),
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }

    def _open_stream():
        client = httpx.Client(timeout=60.0)
        stream = client.stream("POST", GROQ_URL, json=payload, headers=headers)
        try:
            resp = stream.__enter__()
            resp.raise_for_status()
        except BaseException:
            client.close()
            raise
        return client, resp

    # Retrying mid-stream is risky (partial output already emitted), so the
    # retry/backoff only covers establishing the initial connection.
    client, resp = with_retries(_open_stream)

    try:
        for line in resp.iter_lines():
            if not line:
                continue
            if line == "data: [DONE]":
                break
            if line.startswith("data: "):
                try:
                    chunk = json.loads(line[6:])
                    yield chunk
                except json.JSONDecodeError:
                    continue
    finally:
        try:
            resp.__exit__(None, None, None)
        except BaseException:
            pass
        client.close()


def _normalize_ollama_messages(messages: list) -> list:
    """Convert Groq-style tool_calls (arguments as JSON string) to Ollama dict format."""
    normalized = []
    for m in messages:
        if not isinstance(m, dict):
            normalized.append(m)
            continue
        nm = dict(m)
        if "tool_calls" in nm and isinstance(nm["tool_calls"], list):
            new_tcs = []
            for tc in nm["tool_calls"]:
                ntc = dict(tc)
                func = dict(ntc.get("function", {}))
                args = func.get("arguments", "")
                if isinstance(args, str):
                    try:
                        func["arguments"] = json.loads(args) if args.strip() else {}
                    except json.JSONDecodeError:
                        func["arguments"] = {}
                elif args is None:
                    func["arguments"] = {}
                ntc["function"] = func
                new_tcs.append(ntc)
            nm["tool_calls"] = new_tcs
        normalized.append(nm)
    return normalized

def _ollama_request(messages: list, tools: list[dict], system: str, stream: bool = False) -> dict:
    """Low-level Ollama call via /api/chat (OpenAI-compatible tools)."""
    url = _ollama_url()
    out_messages = _normalize_ollama_messages(messages)
    payload = {
        "model": _get_ollama_model(),
        "messages": out_messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + out_messages

    def _do_request():
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload, headers={"User-Agent": USER_AGENT})
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Surface body for debugging (Ollama 400 gives JSON error)
                body = ""
                try:
                    body = resp.text
                except Exception:
                    pass
                raise RuntimeError(f"Ollama API error {resp.status_code}: {body}") from e
            return resp.json()

    return with_retries(_do_request)


def _ollama_stream(messages: list, tools: list[dict], system: str) -> Generator[dict, None, None]:
    """Yield chunks from Ollama streaming /api/chat (ndjson)."""
    url = _ollama_url()
    out_messages = _normalize_ollama_messages(messages)
    payload = {
        "model": _get_ollama_model(),
        "messages": out_messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + out_messages

    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

    def _open_stream():
        client = httpx.Client(timeout=120.0)
        stream = client.stream("POST", url, json=payload, headers=headers)
        try:
            resp = stream.__enter__()
            resp.raise_for_status()
        except BaseException:
            client.close()
            raise
        return client, resp

    client, resp = with_retries(_open_stream)

    try:
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                yield chunk
            except json.JSONDecodeError:
                continue
    finally:
        try:
            resp.__exit__(None, None, None)
        except BaseException:
            pass
        client.close()


class LLMClient:

    def __init__(self, api_key: str | None = None):
        self.provider = get_config().provider

        if self.provider == "groq":
            self.groq_messages = []
            return

        if self.provider == "ollama":
            self.ollama_messages = []
            return

        # Default: Gemini
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Get a free key at "
                "https://aistudio.google.com/apikey and put it in your .env file. "
                "Or set MODEL_PROVIDER=groq and use GROQ_API_KEY instead. "
                "Or set MODEL_PROVIDER=ollama for local Ollama (no key needed)."
            )
        self.client = genai.Client(api_key=api_key)

    def call(self, contents: list, system: str, tools: list[dict]) -> object:
        if self.provider == "groq":
            return self._call_groq(contents, system, tools)
        if self.provider == "ollama":
            return self._call_ollama(contents, system, tools)
        return self._call_gemini(contents, system, tools)

    def set_groq_messages(self, messages: list):
        self.groq_messages = messages

    def set_ollama_messages(self, messages: list):
        self.ollama_messages = messages

    # --- Gemini implementation (unchanged behavior) ---
    def _call_gemini(self, contents, system, tools):
        function_declarations = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
            for t in tools
        ]

        def _do_call():
            return self.client.models.generate_content(
                model=_get_gemini_model(),
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[types.Tool(function_declarations=function_declarations)],
                ),
            )

        return with_retries(_do_call)

    # --- Groq implementation ---
    def _call_groq(self, contents, system, tools):
        # If the caller has set messages directly (from Agent), use them.
        # Otherwise convert Gemini-style contents to OpenAI-style messages.
        if self.groq_messages:
            messages = self.groq_messages
        else:
            messages = []
            for content in contents:
                role = content.role
                text_parts = []
                for part in content.parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        args = json.dumps(dict(fc.args), ensure_ascii=False)
                        text_parts.append(f"tool_call({fc.name}): {args}")
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        resp = fr.response.get("result", "")
                        text_parts.append(f"tool_result({fr.name}): {resp}")
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})

        # Convert tool schemas to OpenAI tools format
        groq_tools = []
        for t in tools:
            groq_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        data = _groq_request(messages, groq_tools, system)
        return data

    # --- Ollama implementation ---
    def _call_ollama(self, contents, system, tools):
        if getattr(self, "ollama_messages", None):
            messages = self.ollama_messages
        else:
            messages = []
            for content in contents:
                role = content.role
                text_parts = []
                for part in content.parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        args = json.dumps(dict(fc.args), ensure_ascii=False)
                        text_parts.append(f"tool_call({fc.name}): {args}")
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        resp = fr.response.get("result", "")
                        text_parts.append(f"tool_result({fr.name}): {resp}")
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})

        ollama_tools = []
        for t in tools:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        data = _ollama_request(messages, ollama_tools, system)
        # Normalize Ollama response to Groq-compatible shape for Agent
        # Ollama returns {"message": {"content": ..., "tool_calls": ...}}
        if "message" in data and "choices" not in data:
            msg = data.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls") or []
            # Convert Ollama tool_calls to Groq format
            groq_tcs = []
            for tc in tool_calls:
                func = tc.get("function", {})
                args = func.get("arguments", {})
                if isinstance(args, dict):
                    args_str = json.dumps(args, ensure_ascii=False)
                else:
                    args_str = str(args)
                groq_tcs.append({
                    "id": func.get("name", "") + "_0",
                    "type": "function",
                    "function": {"name": func.get("name", ""), "arguments": args_str}
                })
            return {"choices": [{"message": {"content": content, "tool_calls": groq_tcs}}]}
        return data

    def call_stream(self, contents, system, tools):
        if self.provider == "groq":
            return self._call_groq(contents, system, tools)
        if self.provider == "ollama":
            return self._call_ollama(contents, system, tools)
        return self._call_gemini(contents, system, tools)

    def stream(self, contents: list, system: str, tools: list[dict]) -> Generator[dict, None, None]:
        """Yield streaming chunks. Each chunk has 'type' ('text' or 'tool_call') and 'data'."""
        if self.provider == "groq":
            yield from self._stream_groq(contents, system, tools)
        elif self.provider == "ollama":
            yield from self._stream_ollama(contents, system, tools)
        else:
            yield from self._stream_gemini(contents, system, tools)

    def _stream_groq(self, contents, system, tools):
        """Stream from Groq, yielding text chunks and complete tool calls."""
        if self.groq_messages:
            messages = self.groq_messages
        else:
            messages = []
            for content in contents:
                role = content.role
                text_parts = []
                for part in content.parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        args = json.dumps(dict(fc.args), ensure_ascii=False)
                        text_parts.append(f"tool_call({fc.name}): {args}")
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        resp = fr.response.get("result", "")
                        text_parts.append(f"tool_result({fr.name}): {resp}")
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})

        groq_tools = []
        for t in tools:
            groq_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        accumulated_text = ""
        tool_calls_acc = {}

        for chunk in _groq_stream(messages, groq_tools, system):
            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            if delta.get("content"):
                text = delta["content"]
                accumulated_text += text
                yield {"type": "text", "data": text}

            if delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.get("id", ""), "name": "", "arguments": ""}
                    if tc.get("id"):
                        tool_calls_acc[idx]["id"] = tc["id"]
                    func = tc.get("function", {})
                    if func.get("name"):
                        tool_calls_acc[idx]["name"] = func["name"]
                    if func.get("arguments"):
                        tool_calls_acc[idx]["arguments"] += func["arguments"]

        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            yield {"type": "tool_call", "data": tc}

    def _stream_ollama(self, contents, system, tools):
        """Stream from Ollama, yielding text chunks and complete tool calls."""
        if getattr(self, "ollama_messages", None):
            messages = self.ollama_messages
        else:
            messages = []
            for content in contents:
                role = content.role
                text_parts = []
                for part in content.parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        args = json.dumps(dict(fc.args), ensure_ascii=False)
                        text_parts.append(f"tool_call({fc.name}): {args}")
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        resp = fr.response.get("result", "")
                        text_parts.append(f"tool_result({fr.name}): {resp}")
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})

        ollama_tools = []
        for t in tools:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        tool_calls_acc = {}

        for chunk in _ollama_stream(messages, ollama_tools, system):
            msg = chunk.get("message", {})
            if msg.get("content"):
                yield {"type": "text", "data": msg["content"]}
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args = func.get("arguments", {})
                    if isinstance(args, dict):
                        args_str = json.dumps(args, ensure_ascii=False)
                    else:
                        args_str = str(args)
                    tool_calls_acc[name] = {"id": name, "name": name, "arguments": args_str}
            if chunk.get("done") and tool_calls_acc:
                for tc in tool_calls_acc.values():
                    yield {"type": "tool_call", "data": tc}
                tool_calls_acc = {}

        # In case non-streaming done without done flag handling
        for tc in tool_calls_acc.values():
            yield {"type": "tool_call", "data": tc}

    def _gemini_stream_factory(self, contents, system, tools):
        """Return the raw Gemini streaming generator (factory for retry wrapper)."""
        function_declarations = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
            for t in tools
        ]
        return self.client.models.generate_content_stream(
            model=_get_gemini_model(),
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=function_declarations)],
            ),
        )

    def _stream_gemini(self, contents, system, tools):
        """Stream from Gemini, yielding text chunks and complete tool calls."""
        stream = with_retries_stream(self._gemini_stream_factory, contents, system, tools)

        for chunk in stream:
            if not chunk.candidates:
                continue
            candidate = chunk.candidates[0]
            if not candidate.content:
                continue

            for part in candidate.content.parts:
                if getattr(part, "text", None) and part.text:
                    yield {"type": "text", "data": part.text}
                elif getattr(part, "function_call", None):
                    fc = part.function_call
                    yield {
                        "type": "tool_call",
                        "data": {
                            "id": fc.name,
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args), ensure_ascii=False),
                        },
                    }
