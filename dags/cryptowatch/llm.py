"""Thin LLM boundary. Everything else depends on the `LLM` protocol, never on a vendor SDK, so tests run
with FakeLLM (no network, no cost, deterministic) and the provider can be swapped in one place."""
from __future__ import annotations

import os
from typing import Callable, Protocol


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 500) -> str: ...


class AnthropicLLM:
    def __init__(self, model: str, api_key: str | None = None, timeout: float = 30.0):
        import anthropic                                       # lazy: DAG parse must not import the SDK
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("no Anthropic API key configured")
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=3)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 500) -> str:
        try:
            msg = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, temperature=0,
                system=system, messages=[{"role": "user", "content": user}])
        except Exception as exc:                               # noqa: BLE001
            raise LLMError(str(exc)[:200]) from None
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


class FakeLLM:
    """Scripted replies for tests. `reply` is a string, a list (consumed in order) or a callable."""

    def __init__(self, reply: str | list[str] | Callable[[str, str], str]):
        self.reply, self.calls = reply, []

    def complete(self, system: str, user: str, max_tokens: int = 500) -> str:
        self.calls.append({"system": system, "user": user})
        if callable(self.reply):
            return self.reply(system, user)
        if isinstance(self.reply, list):
            return self.reply.pop(0)
        return self.reply
