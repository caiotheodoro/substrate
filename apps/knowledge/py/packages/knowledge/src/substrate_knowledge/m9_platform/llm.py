"""A-K-37 llm-provider-abstraction.

Every LLM touchpoint in 04 goes through this module: an OpenAI-compatible
HTTP client (default Ollama :11434) with embeddings and structured-output
negotiation, and a fully deterministic stub backend used by tests and
offline CLI runs. Frontier models are reachable only via `SUBSTRATE_PEAK_*`
env keys and are never a runtime dependency.

Structured-output negotiation:
  1. try OpenAI `response_format: json_schema` (strict);
  2. on provider error, retry with the schema as JSON-in-prompt instructions;
  3. parse with pydantic `model_validate_json`.
"""

from __future__ import annotations

import os
from typing import Any, TypeVar

import numpy as np
from pydantic import BaseModel, ValidationError

from substrate_knowledge.core.text import hash_embed

T = TypeVar("T", bound=BaseModel)

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_EMBED_MODEL = "nomic-embed-text"


class LLMError(RuntimeError):
    """Provider failure (network, schema negotiation, parse)."""


class LLMProvider:
    """OpenAI-compatible provider wrapper.

    `stub=True` (or env `KNOW_LLM_STUB=1`) selects the deterministic
    backend: completions become a content-addressed canned string,
    embeddings become hashing-trick vectors. The HTTP client is created
    lazily so constructing a provider never touches the network.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        stub: bool | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("KNOW_LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("KNOW_LLM_MODEL") or DEFAULT_MODEL
        self.embed_model = embed_model or os.environ.get("KNOW_LLM_EMBED_MODEL") or DEFAULT_EMBED_MODEL
        self.api_key = api_key or os.environ.get("KNOW_LLM_API_KEY")
        self.timeout = timeout
        if stub is None:
            stub = os.environ.get("KNOW_LLM_STUB", "0") == "1"
        self.stub = stub
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # HTTP plumbing (lazy)
    # ------------------------------------------------------------------
    def _http(self) -> Any:
        if self._client is None:
            import httpx

            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout, headers=headers)
        return self._client

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        try:
            resp = self._http().post(path, json=payload)
        except Exception as exc:  # httpx.TransportError family
            raise LLMError(f"llm transport failure on {path}: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"llm provider error {resp.status_code} on {path}: {resp.text[:200]}")
        return resp.json()

    # ------------------------------------------------------------------
    # Completions
    # ------------------------------------------------------------------
    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 512) -> str:
        """Plain chat completion. Returns the assistant content string."""
        if self.stub:
            return self._stub_complete(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = self._post_json("/chat/completions", payload)
        try:
            return data["choices"][0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected completion shape: {data}") from exc

    def structured(self, response_model: type[T], prompt: str) -> T:
        """Type-constrained completion with response-format negotiation."""
        if self.stub:
            return self._stub_structured(response_model, prompt)
        schema = response_model.model_json_schema()
        schema_payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": response_model.__name__, "strict": True, "schema": schema},
            },
        }
        try:
            text = self._post_json("/chat/completions", schema_payload)["choices"][0]["message"]["content"]
        except LLMError:
            plain_payload = dict(schema_payload)
            plain_payload.pop("response_format")
            plain_payload["messages"] = [
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\nRespond with a single JSON object strictly matching this JSON schema: "
                        f"{schema}"
                    ),
                }
            ]
            text = self._post_json("/chat/completions", plain_payload)["choices"][0]["message"]["content"]
        try:
            return response_model.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(f"structured output failed schema validation: {exc}") from exc

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def embed(self, text: str) -> np.ndarray:
        if self.stub:
            return hash_embed(text)
        data = self._post_json("/embeddings", {"model": self.embed_model, "input": text})
        try:
            return np.asarray(data["data"][0]["embedding"], dtype=np.float64)  # type: ignore[index]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected embedding shape: {data}") from exc

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        return [self.embed(t) for t in texts]

    # ------------------------------------------------------------------
    # Deterministic stub backend
    # ------------------------------------------------------------------
    @staticmethod
    def _stub_complete(messages: list[dict[str, str]]) -> str:
        import hashlib

        joined = "|".join(m.get("content", "") for m in messages)
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
        return f"deterministic stub completion [{digest}]"

    @staticmethod
    def _stub_structured(response_model: type[T], prompt: str) -> T:
        """Deterministic structured output: the model instance with defaults.

        Design decision: the stub cannot fabricate semantically correct
        content; it returns the fully-defaulted instance so downstream
        protocol code (validation, telemetry, negotiation paths) is
        exercisable offline. Real extraction/verdict logic has its own
        deterministic stubs (PatternExtractor, DeterministicVerdictClassifier)
        which do not route through here.
        """
        try:
            return response_model()
        except ValidationError:
            fields = {name: None for name in response_model.model_fields}
            return response_model.model_construct(**fields)


def create_provider() -> LLMProvider:
    """Env-driven factory: `KNOW_LLM_BASE_URL`, `KNOW_LLM_MODEL`, `KNOW_LLM_STUB`."""
    return LLMProvider()


def hash_embed_embedder(text: str) -> np.ndarray:
    """Module-level embedder alias used by stores that accept callables."""
    return hash_embed(text)
