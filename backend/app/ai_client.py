"""One client for any OpenAI-compatible chat API, chosen by settings. Only text is ever sent."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx

from app.config import get_settings


class AiError(Exception):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class Provider:
    name: str
    model: str


def provider() -> Provider:
    settings = get_settings()
    if settings.ai_provider == "openai_compatible" and settings.ai_api_key:
        return Provider("openai_compatible", settings.ai_model)
    return Provider("stub", "template")


def cost_usd(usage: Usage) -> float:
    settings = get_settings()
    return (usage.input_tokens * settings.ai_input_usd_per_million
            + usage.output_tokens * settings.ai_output_usd_per_million) / 1_000_000


def stream_chat(system: str, user: str, usage: Usage, stub: Callable[[], str]) -> Iterator[str]:
    """Yields text chunks of the reply and fills `usage` when the provider reports it. `stub` makes
    the reply locally when no provider is configured."""
    if provider().name == "stub":
        reply = stub()
        usage.input_tokens, usage.output_tokens = len(system + user) // 4, len(reply) // 4
        for i in range(0, len(reply), 48):
            yield reply[i:i + 48]
        return

    settings = get_settings()
    body = {
        "model": settings.ai_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
    }
    headers = {"Authorization": f"Bearer {settings.ai_api_key}"}
    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client, client.stream(
            "POST", f"{settings.ai_base_url.rstrip('/')}/chat/completions", json=body, headers=headers
        ) as response:
            if response.status_code != 200:
                raise AiError(f"provider answered {response.status_code}")
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("usage"):
                    usage.input_tokens = event["usage"].get("prompt_tokens", 0) or 0
                    usage.output_tokens = event["usage"].get("completion_tokens", 0) or 0
                for choice in event.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece
    except (httpx.HTTPError, ValueError) as exc:
        raise AiError(type(exc).__name__) from None


class TextTap:
    """Pulls the human-readable string values out of a JSON reply as it streams, so the Studio can
    show real text being written instead of raw JSON."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.expect_key = False
        self.in_string = False
        self.is_value = False
        self.escape: str | None = None

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            if self.in_string:
                if self.escape is not None:
                    self.escape += ch
                    if self.escape[0] == "u":
                        if len(self.escape) < 5:
                            continue
                        try:
                            decoded = chr(int(self.escape[1:], 16))
                        except ValueError:
                            decoded = ""
                    else:
                        decoded = {"n": "\n", "t": " ", "r": ""}.get(ch, ch)
                    self.escape = None
                    if self.is_value:
                        out.append(decoded)
                elif ch == "\\":
                    self.escape = ""
                elif ch == '"':
                    self.in_string = False
                    if self.is_value:
                        out.append("\n")
                elif self.is_value:
                    out.append(ch)
                continue
            if ch == '"':
                self.in_string = True
                self.is_value = not (self.stack and self.stack[-1] == "{" and self.expect_key)
            elif ch in "{[":
                self.stack.append(ch)
                self.expect_key = ch == "{"
            elif ch in "}]":
                if self.stack:
                    self.stack.pop()
                self.expect_key = False
            elif ch == ":":
                self.expect_key = False
            elif ch == ",":
                self.expect_key = bool(self.stack) and self.stack[-1] == "{"
        return "".join(out)


def parse_json(reply: str) -> dict:
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end < start:
        raise AiError("no JSON object in reply")
    try:
        value = json.loads(reply[start:end + 1])
    except ValueError:
        raise AiError("reply is not valid JSON") from None
    if not isinstance(value, dict):
        raise AiError("reply is not a JSON object")
    return value
