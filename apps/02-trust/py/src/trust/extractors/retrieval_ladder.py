"""A-T-15 retrieval-verdict ladder — HHEM-2.1 (CPU, always-on) → Glider-3.8B
→ Lynx-8B, cheap-first.

The ladder is a protocol over ``VerdictModelProtocol`` rungs (see
``trust.model_backend``): the cheap rung always answers, and a low-probability
verdict escalates to the next rung. Verdict probabilities are raw model
outputs here; they are recalibrated by the same netcal pipeline as the scorer
before they become features. Tests use deterministic rungs; the Ollama/llama.cpp
rungs are wired through ``OllamaVerdictBackend`` and never required offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trust.contracts import RetrievalVerdict
from trust.model_backend import OllamaVerdictBackend, VerdictModelProtocol

HHEM_2_1 = "hhem-2.1"
GLIDER_3_8B = "glider-3.8b"
LYNX_8B = "lynx-8b"


@dataclass(frozen=True)
class LadderRung:
    name: str
    model: VerdictModelProtocol
    escalate_below: float = 0.75


@dataclass
class LadderTrace:
    rungs_used: list[str] = field(default_factory=list)
    verdict: RetrievalVerdict | None = None


class RetrievalLadder:
    """Cheap-first verdict ladder. HHEM-2.1 always runs; escalation is
    triggered when a rung's probability falls below its ``escalate_below``
    threshold (a low-prob verdict is an uncertain verdict)."""

    def __init__(self, rungs: list[LadderRung]) -> None:
        if not rungs:
            raise ValueError("ladder needs at least one rung")
        self._rungs = rungs

    def verdict(self, claim: str, passages: list[str], temperature: float = 0.0) -> tuple[RetrievalVerdict, LadderTrace]:
        trace = LadderTrace()
        best: RetrievalVerdict | None = None
        for rung in self._rungs:
            trace.rungs_used.append(rung.name)
            verdict = rung.model.verdict(claim, passages, temperature)
            if best is None or verdict.prob > best.prob:
                best = verdict
            if verdict.prob >= rung.escalate_below:
                break
        trace.verdict = best
        return best, trace

    @property
    def rungs(self) -> list[LadderRung]:
        return list(self._rungs)


def build_llm_ladder(base_url_ollama: str = "http://localhost:11434", base_url_llama: str = "http://localhost:8080") -> RetrievalLadder:
    """Production ladder: HHEM-2.1 always-on (llama.cpp :8080), escalating to
    Glider-3.8B then Lynx-8B. Requires the compose models — never in tests."""
    hhem = OllamaVerdictBackend(HHEM_2_1, model="hhem-2.1", base_url=base_url_llama)
    glider = OllamaVerdictBackend(GLIDER_3_8B, model="glider-3.8b", base_url=base_url_ollama)
    lynx = OllamaVerdictBackend(LYNX_8B, model="lynx-8b", base_url=base_url_ollama)
    return RetrievalLadder(
        [
            LadderRung(HHEM_2_1, hhem, escalate_below=0.75),
            LadderRung(GLIDER_3_8B, glider, escalate_below=0.85),
            LadderRung(LYNX_8B, lynx, escalate_below=1.01),
        ]
    )


def summarize_ladder_verdict(verdict: RetrievalVerdict) -> dict[str, Any]:
    """The C3 summary that becomes the A-T-17 retrieval feature group."""
    return verdict.as_dict()
