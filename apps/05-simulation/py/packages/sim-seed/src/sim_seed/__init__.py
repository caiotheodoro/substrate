"""M5 — Seed-material synthesizer: macro snapshot → versioned world doc
(A-S-20 svc :8302) with seed-schema validation + coherence lint (A-S-21)."""

from .schema import (
    CURRENT_SCHEMA_VERSION,
    WORLD_DOC_SCHEMA,
    coherence_lint,
    validate_world_doc,
)
from .synth import SeedSynthesizer, PromptTemplate, PROMPT_VERSION
from .app import app as seed_synth_app

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "WORLD_DOC_SCHEMA",
    "coherence_lint",
    "validate_world_doc",
    "SeedSynthesizer",
    "PromptTemplate",
    "PROMPT_VERSION",
    "seed_synth_app",
]