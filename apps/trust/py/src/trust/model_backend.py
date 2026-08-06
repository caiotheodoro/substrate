"""Model backends behind an interface — every LLM touchpoint in 02 goes
through an OpenAI-compatible client (default Ollama :11434, verdict models via
llama.cpp ``llama serve`` :8080). Stub backends keep tests deterministic and
offline. No model downloads ever happen here.
"""
from __future__ import annotations

import math
import random
from typing import Any, Protocol

from trust.contracts import RetrievalVerdict


class LLMBackend(Protocol):
    """OpenAI-compatible chat completion endpoint."""

    kind: str

    def complete(self, messages: list[dict[str, Any]], max_tokens: int = 64, temperature: float = 0.0) -> str: ...
    def logprob(self, prompt: str, completion: str) -> float | None:
        """Banned-by-hierarchy; exposed for A-T-12 baselines only."""
        ...


class OllamaBackend:
    """OpenAI-compatible client against Ollama (``http://localhost:11434``)."""

    kind = "ollama"

    def __init__(self, model: str = "llama3.1:8b", base_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.base_url = base_url

    def _client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("openai client not installed") from e
        return OpenAI(base_url=f"{self.base_url}/v1", api_key="ollama")

    def complete(self, messages: list[dict[str, Any]], max_tokens: int = 64, temperature: float = 0.0) -> str:
        return self._client().chat.completions.create(
            model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature
        ).choices[0].message.content  # type: ignore[union-attr]

    def embeddings(self, texts: list[str]) -> list[list[float]]:
        resp = self._client().embeddings.create(model="nomic-embed-text", input=texts)
        return [d.embedding for d in resp.data]  # type: ignore[union-attr]

    def logprob(self, prompt: str, completion: str) -> float | None:
        client = self._client()
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=len(completion) + 8,
            temperature=0.0,
            logprobs=True,
        ).choices[0]  # type: ignore[union-attr]
        if not resp.logprobs or not resp.logprobs.content:
            return None
        tokens = resp.logprobs.content
        # sum the logprobs of the completion token sequence
        total = 0.0
        for tl in tokens:
            for alt in tl.top_logprobs:
                if alt.token == completion:  # pragmatic match
                    total += alt.logprob
                    break
        return float(total)


class StubLLMBackend:
    """Deterministic fake: echoes a canned mapping; used ONLY in tests."""

    kind = "stub"

    def __init__(self, answers: dict[str, str] | None = None, prob_override: float | None = None) -> None:
        self.answers = answers or {}
        self.prob_override = prob_override

    def scope_deterministic_dispatch(self, key: str) -> str:
        return self.answers.get(key, "UNKNOWN")

    def complete(self, messages: list[dict[str, Any]], max_tokens: int = 64, temperature: float = 0.0) -> str:
        h = messages[-1]["content"] if messages else ""
        return self.answers.get(h, "UNKNOWN")

    def logprob(self, prompt: str, completion: str) -> float | None:
        # Deterministic synthetic: higher for "canonical" completions (never a
        # production feature — A-T-12 baseline only).
        if self.prob_override is not None:
            return self.prob_override
        seed = abs(hash((prompt, completion))) % 1000 / 1000.0
        return math.log(0.3 + 0.6 * seed)


class VerdictModelProtocol(Protocol):
    """One rung of the A-T-15 ladder (HHEM-2.1 → Glider → Lynx)."""

    name: str

    def verdict(self, claim: str, passages: list[str], temperature: float = 0.0) -> RetrievalVerdict: ...


class OllamaVerdictBackend:
    """OpenAI-compatible verdict model (HHEM via llama.cpp :8080)."""

    name = ""

    def __init__(self, name: str, model: str, base_url: str = "http://localhost:8080", backend: LLMBackend | None = None) -> None:
        self.name = name
        self._backend = backend or OllamaBackend(model=model, base_url=base_url)

    def verdict(self, claim: str, passages: list[str], temperature: float = 0.0) -> RetrievalVerdict:
        context = "\n".join(f"[{i}] {p}" for i, p in enumerate(passages))
        out = self._backend.complete(
            [
                {"role": "system", "content": "Return JSON {kind: support|contradict|silent, prob: 0..1, citedEvidence: source{...}}."},
                {"role": "user", "content": f"CLAIM: {claim}\nPASSAGES:\n{context}"},
            ],
            max_tokens=128,
            temperature=temperature,
        )
        return parse_verdict_json(out, claim)


def parse_verdict_json(text: str, claim: str) -> RetrievalVerdict:
    """Lenient JSON parse → C3 shape. Malformed output defaults to ``silent``
    with prob 0.5 (escalation bias is handled by calibration later)."""
    import json
    import re

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return RetrievalVerdict("silent", 0.5, None, claim)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return RetrievalVerdict("silent", 0.5, None, claim)
    kind = data.get("kind")
    if kind not in ("support", "contradict", "silent"):
        return RetrievalVerdict("silent", 0.5, None, claim)
    prob = min(1.0, max(0.0, float(data.get("prob", 0.5))))
    ev = data.get("citedEvidence")
    return RetrievalVerdict(kind, prob, str(ev) if ev else None, claim)


class DeterministicVerdictBackend:
    """Test-double verdict: probability derived from text overlap of claim and
    passage (+ signed support/refute keywords). No network."""

    name = "deterministic-stub"

    def __init__(self, floor: float = 0.05, noise: float = 0.0) -> None:
        self.floor = floor
        self.noise = noise

    def verdict(self, claim: str, passages: list[str], temperature: float = 0.0) -> RetrievalVerdict:
        rng = random.Random(abs(hash((claim, tuple(passages)))) % (2**32))
        best = None
        cset = set(w.lower() for w in claim.split())
        for p in passages:
            pset = set(w.lower() for w in p.split())
            ov = len(cset & pset) / max(1, len(cset))
            kind: str = "silent"
            if any(k in p.lower() for k in ("not", "no", "contradict", "refutes", "contrary")):
                kind = "contradict"
            elif any(k in p.lower() for k in ("support", "confirm", "consistent", "indeed")):
                kind = "support"
            elif ov > 0.3:
                kind = "support"
            prob = max(self.floor, min(0.99, ov * 0.9 + self.noise * rng.random()))
            cand = RetrievalVerdict(kind, prob, p.split()[0], claim)  # type: ignore[arg-type]
            if best is None or prob > best.prob:
                best = cand
        return best or RetrievalVerdict("silent", self.floor, None, claim)