"""Cross-cutting primitives shared by all 05 molecules.

C1-faithful canonical JSON + chain hashing, the seeded RNG registry
(A-S-18), the OpenAI-compatible LLM client (Ollama default / LiteLLM),
and the per-agent per-round cost meter (A-S-35).
"""

from .canonical import canonical_json, chain_hash, idempotency_key
from .rng import SeededRNG, RNGRegistry
from .llm import OpenAICompatClient, LLMUnavailableError
from .cost import CostMeter, CostLedgerEntry, CostSummary, CostCeiling

__all__ = [
    "canonical_json",
    "chain_hash",
    "idempotency_key",
    "SeededRNG",
    "RNGRegistry",
    "OpenAICompatClient",
    "LLMUnavailableError",
    "CostMeter",
    "CostLedgerEntry",
    "CostSummary",
    "CostCeiling",
]
