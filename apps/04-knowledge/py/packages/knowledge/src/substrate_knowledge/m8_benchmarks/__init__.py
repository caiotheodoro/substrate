"""M8 — benchmarks: R1 graph-vs-flat (existing), R2 error propagation, R5 QA."""

from substrate_knowledge.m8_benchmarks.error_propagation import ErrorPropagationRunner, PropagationPoint
from substrate_knowledge.m8_benchmarks.retrieval_qa import (
    RetrievalQARunner,
    context_precision,
    faithfulness,
)

__all__ = [
    "ErrorPropagationRunner",
    "PropagationPoint",
    "RetrievalQARunner",
    "context_precision",
    "faithfulness",
]
