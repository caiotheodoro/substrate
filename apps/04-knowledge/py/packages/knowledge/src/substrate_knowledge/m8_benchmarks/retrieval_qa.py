"""A-K-35 retrieval-qa-suite — RAGAS-style metrics + MultiHop-RAG-style tasks.

Metrics implemented here (deterministic approximations, no LLM):
  - faithfulness: fraction of answer claims (gold answer phrases) whose
    tokens appear in the retrieved evidence;
  - context-precision: rank-aware precision of the retrieved context w.r.t.
    the gold evidence docs;
  - answer accuracy: fraction of questions whose full gold evidence was
    retrieved.

The multi-hop corpus IS the MultiHop-RAG-style task set (joins across two
documents). The runner wires a retriever (graph or flat) to produce ranked
context; scores are asserted to lie in [0, 1] by the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from substrate_knowledge.core.text import tokenize
from substrate_knowledge.m8_benchmarks.corpora import SyntheticCorpus
from substrate_knowledge.m8_benchmarks.graph_vs_flat import GraphVsFlatRunner


def faithfulness(claims: list[str], evidence: list[str]) -> float:
    """Fraction of claim tokens supported by the evidence text."""
    if not claims:
        return 0.0
    evidence_tokens: set[str] = set()
    for text in evidence:
        evidence_tokens |= set(tokenize(text))
    scores = []
    for claim in claims:
        claim_tokens = set(tokenize(claim))
        if not claim_tokens:
            scores.append(1.0)
            continue
        scores.append(len(claim_tokens & evidence_tokens) / len(claim_tokens))
    return sum(scores) / len(scores)


def context_precision(retrieved: list[str], relevant: set[str], k: int | None = None) -> float:
    """Average precision over retrieved documents: at each rank where a
    relevant document appears, precision@rank is summed and averaged over
    the number of relevant documents."""
    if not relevant:
        return 0.0
    if k is not None:
        retrieved = retrieved[:k]
    hits_at = []
    precision_sum = 0.0
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            hits_at.append(rank)
            precision_sum += sum(1 for r in retrieved[:rank] if r in relevant) / rank
    if not hits_at:
        return 0.0
    return precision_sum / len(relevant)


@dataclass
class QAItemResult:
    question: str
    answer_correct: bool
    faithfulness: float
    context_precision: float
    retrieved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer_correct": self.answer_correct,
            "faithfulness": round(self.faithfulness, 4),
            "context_precision": round(self.context_precision, 4),
            "retrieved": self.retrieved,
        }


@dataclass
class QASuiteReport:
    corpus: str
    mode: str
    n_questions: int
    answer_accuracy: float
    mean_faithfulness: float
    mean_context_precision: float
    items: list[QAItemResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "corpus": self.corpus,
            "mode": self.mode,
            "n_questions": self.n_questions,
            "answer_accuracy": round(self.answer_accuracy, 4),
            "mean_faithfulness": round(self.mean_faithfulness, 4),
            "mean_context_precision": round(self.mean_context_precision, 4),
            "items": [i.to_dict() for i in self.items],
        }


class RetrievalQARunner:
    def __init__(self, budget: int = 2, retriever: Callable | None = None) -> None:
        self.budget = budget
        self._runner = GraphVsFlatRunner(budget=budget)
        self._retriever = retriever

    def run(self, corpus: SyntheticCorpus, mode: str = "graph") -> QASuiteReport:
        self._runner.run(corpus)  # initializes the flat/graph retrievers
        items: list[QAItemResult] = []
        for qa in corpus.qa:
            if self._retriever is not None:
                retrieved = self._retriever(qa.question, self.budget)
            elif mode == "flat":
                retrieved = self._runner._flat_retrieve(qa.question, self.budget)
            else:
                retrieved = self._runner._graph_retrieve(qa.question, self.budget)
            relevant = set(qa.evidence_docs)
            answer_correct = bool(relevant) and relevant.issubset(set(retrieved))
            evidence_texts = [d.text for d in corpus.docs if d.doc_id in retrieved]
            claims = [qa.gold_answer]
            items.append(
                QAItemResult(
                    question=qa.question,
                    answer_correct=answer_correct,
                    faithfulness=faithfulness(claims, evidence_texts),
                    context_precision=context_precision(retrieved, relevant),
                    retrieved=retrieved,
                )
            )
        n = len(items)
        return QASuiteReport(
            corpus=corpus.name,
            mode=mode,
            n_questions=n,
            answer_accuracy=sum(i.answer_correct for i in items) / n if n else 0.0,
            mean_faithfulness=sum(i.faithfulness for i in items) / n if n else 0.0,
            mean_context_precision=sum(i.context_precision for i in items) / n if n else 0.0,
            items=items,
        )
