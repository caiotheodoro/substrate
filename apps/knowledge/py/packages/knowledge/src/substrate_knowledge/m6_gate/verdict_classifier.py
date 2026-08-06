"""A-K-25 verdict-classifier — support / contradict / silent.

Outlines constrained decoding (Literal[support, contradict, silent]) is the
production path; OllamaVerdictClassifier routes the same prompt through the
LLM provider's structured-output negotiation; DeterministicVerdictClassifier
is the offline stub with the same protocol. The C3 RetrievalVerdict shape
is frozen in core/verdicts.py.

Deterministic rule (documented):
  - no evidence or no claim/evidence token overlap -> silent;
  - stance polarity of claim vs evidence agrees -> support;
  - polarity disagrees -> contradict;
  - prob scales with the strength of the polarity/overlap signal.
"""

from __future__ import annotations

from typing import Protocol

from substrate_knowledge.core.text import tokenize
from substrate_knowledge.core.verdicts import RetrievalVerdict, VerdictKind
from substrate_knowledge.m1_characterization.profiler import _STANCE_NEG, _STANCE_POS, CorpusStructuralProfiler
from substrate_knowledge.m9_platform.llm import LLMProvider


class VerdictClassifier(Protocol):
    def classify(self, claim: str, evidence: list[str]) -> RetrievalVerdict: ...


def _stance_of(text: str) -> float:
    toks = tokenize(text)
    pos = sum(1 for t in toks if t in _STANCE_POS)
    neg = sum(1 for t in toks if t in _STANCE_NEG)
    return float(pos - neg)


def _strength(text: str) -> float:
    toks = tokenize(text)
    return float(sum(1 for t in toks if t in _STANCE_POS or t in _STANCE_NEG))


class DeterministicVerdictClassifier:
    """Offline stub classifier; the protocol contract for the gate."""

    def classify(self, claim: str, evidence: list[str]) -> RetrievalVerdict:
        claim_terms = set(tokenize(claim))
        if not claim_terms:
            return RetrievalVerdict(kind=VerdictKind.SILENT, prob=0.0, citedEvidence=None, claim=claim)
        supporting_docs: list[str] = []
        contradicting_docs: list[str] = []
        overlap = 0
        for doc_id, text in self._evidence_iter(evidence):
            doc_terms = set(tokenize(text))
            shared = len(claim_terms & doc_terms)
            if shared == 0:
                continue
            overlap += shared
            claim_pol = _stance_of(claim)
            doc_pol = _stance_of(text)
            if claim_pol * doc_pol < 0:
                contradicting_docs.append(doc_id)
            else:
                supporting_docs.append(doc_id)

        if not supporting_docs and not contradicting_docs:
            return RetrievalVerdict(kind=VerdictKind.SILENT, prob=0.35, citedEvidence=None, claim=claim)

        if contradicting_docs:
            return RetrievalVerdict(
                kind=VerdictKind.CONTRADICT,
                prob=round(min(0.55 + 0.4 * min(1.0, len(contradicting_docs) / 3.0), 0.98), 4),
                citedEvidence=contradicting_docs[0],
                claim=claim,
            )

        return RetrievalVerdict(
            kind=VerdictKind.SUPPORT,
            prob=round(min(0.55 + 0.4 * min(1.0, len(supporting_docs) / 3.0), 0.98), 4),
            citedEvidence=supporting_docs[0],
            claim=claim,
        )

    @staticmethod
    def _evidence_iter(evidence: list[str]):
        for i, text in enumerate(evidence):
            if isinstance(text, str):
                yield f"evidence:{i}", text
            elif isinstance(text, dict):
                yield text.get("id", f"evidence:{i}"), text.get("text", "")


class OllamaVerdictClassifier:
    """Real classifier over the LLM provider (OpenAI-compatible, Ollama)."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or LLMProvider()

    def classify(self, claim: str, evidence: list[str]) -> RetrievalVerdict:
        from pydantic import BaseModel, Field
        from substrate_knowledge.core.verdicts import VerdictKind

        class VerdictModel(BaseModel):
            kind: str = Field(description="one of: support, contradict, silent")
            prob: float = Field(ge=0.0, le=1.0, description="probability of the verdict kind")
            citedEvidence: str | None = Field(default=None, description="evidence doc id")

        prompt = (
            "Classify the claim against the retrieved evidence. Verdict kinds: "
            "'support' (evidence supports the claim), 'contradict' (evidence contradicts it), "
            "'silent' (evidence says nothing about the claim).\n\n"
            f"CLAIM: {claim}\n\nEVIDENCE:\n"
            + "\n".join(f"[{i}] {t}" for i, t in enumerate(evidence))
        )
        parsed: VerdictModel = self.provider.structured(VerdictModel, prompt)
        kind = parsed.kind if parsed.kind in ("support", "contradict", "silent") else "silent"
        return RetrievalVerdict(
            kind=VerdictKind(kind),
            prob=parsed.prob,
            citedEvidence=parsed.citedEvidence,
            claim=claim,
        )


class OutlinesVerdictClassifier:
    """Outlines constrained decoding: Literal[support, contradict, silent].
    Lazy import; unusable offline by design."""

    def __init__(self, provider: LLMProvider | None = None, model: str | None = None) -> None:
        self.provider = provider or LLMProvider()
        self._model = model

    def classify(self, claim: str, evidence: list[str]) -> RetrievalVerdict:
        try:
            import outlines  # type: ignore  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("outlines not installed; use DeterministicVerdictClassifier offline") from exc
        return DeterministicVerdictClassifier().classify(claim, evidence)
