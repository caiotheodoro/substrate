"""OpenAI-compatible LLM client (PLAN.md: every LLM touchpoint goes through an
OpenAI-compatible client). Default = Ollama :11434; LiteLLM :4000 via env.

Peak/frontier models are env-key gated (`SUBSTRATE_PEAK_*`) and are NEVER a
runtime dependency — requesting a model without its key configured raises
LLMUnavailableError. All network I/O is behind this interface so tests stub
`complete(...)` instead of hitting a socket.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx


class LLMUnavailableError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1"))
    api_key: str | None = field(default_factory=lambda: os.environ.get("LLM_API_KEY"))
    default_model: str = field(
        default_factory=lambda: os.environ.get("SUBSTRATE_LLM_MODEL", "qwen2.5:0.5b")
    )
    timeout_s: float = 60.0


@dataclass
class LLMUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


@dataclass
class LLMResponse:
    text: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)


class OpenAICompatClient:
    """Minimal OpenAI /chat/completions client. Thread-safe for sync use."""

    def __init__(self, config: LLMConfig | None = None, transport: httpx.BaseTransport | None = None):
        self.config = config or LLMConfig()
        self.http = httpx.Client(
            base_url=self.config.base_url,
            headers={"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {},
            timeout=httpx.Timeout(self.config.timeout_s),
            transport=transport,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model or self.config.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with self.http.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code != 200:
                raise LLMUnavailableError(
                    f"LLM endpoint {self.config.base_url} returned {resp.status_code}: {resp.text[:200]}"
                )
            body = resp.json()
        choice = body["choices"][0]
        usage = body.get("usage", {})
        return LLMResponse(
            text=choice["message"]["content"],
            model=body.get("model", payload["model"]),
            usage=LLMUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                cached_input_tokens=usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
                if isinstance(usage.get("prompt_tokens_details"), dict)
                else 0,
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=int(resp.headers.get("x-llm-latency-ms", 0) or 0),
            ),
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "OpenAICompatClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def required_peak_key(model_prefix: str) -> str:
    """Peak-model gate: frontier calls require a configured env key."""
    key = os.environ.get("SUBSTRATE_PEAK_API_KEY")
    if not key:
        raise LLMUnavailableError(
            f"peak model `{model_prefix}` requires SUBSTRATE_PEAK_API_KEY (never a runtime dependency)"
        )
    return key