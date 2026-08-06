"""A-S-20 seed-synth: macro snapshot → narrative world doc via an
OpenAI-compatible client (Ollama default / LiteLLM :4000). The client is
injected/stubbed in tests — no network-dependent tests (unit constraint).

Templates are versioned (`PROMPT_VERSION`) and the prompt enforces the
no-lookahead discipline: the model only ever sees the snapshot as of
`as_of` and is told to describe the world as it was known then.
"""

from __future__ import annotations

import json

import httpx
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sim_shared.llm import LLMUnavailableError, OpenAICompatClient

from .schema import CURRENT_SCHEMA_VERSION, coherence_lint, validate_world_doc

PROMPT_VERSION = "1.0.0"

NARRATIVE_SECTIONS = ("economy", "labor", "consumers", "supply_chain", "sentiment")


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    system: str
    user: str

    def messages(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        series_lines = "\n".join(
            f"- {row['series_id']}: {row['value']}{row.get('units', '')}"
            for row in snapshot["series"]
        )
        user = self.user.format(
            as_of=snapshot["as_of"],
            series=series_lines,
            world_id=snapshot.get("world_id", "world"),
        )
        return [{"role": "system", "content": self.system}, {"role": "user", "content": user}]


TEMPLATES: dict[str, PromptTemplate] = {
    "1.0.0": PromptTemplate(
        version="1.0.0",
        system=(
            "You write the 'state of the world' seed material for a behavioral simulation. "
            "You may ONLY describe the world as it was known on the given as-of date. "
            "You must not mention events, data, or outcomes after that date — no hindsight. "
            "Write five short narrative sections (economy, labor, consumers, supply_chain, "
            "sentiment), each 1-3 sentences, grounded in the numeric snapshot provided. "
            "Return strict JSON with keys: narrative, inferred_risks."
        ),
        user=(
            "Macro snapshot as of {as_of} (world id: {world_id}):\n{series}\n\n"
            "Return JSON: {{\"narrative\": {{\"economy\": str, \"labor\": str, "
            "\"consumers\": str, \"supply_chain\": str, \"sentiment\": str}}, "
            "\"inferred_risks\": {{\"cascade\": float 0-1, \"shift_magnitude\": float 0-1}}}}"
        ),
    ),
}


class SeedSynthesizer:
    """Versioned world-doc synthesis; output validated by seed-schema."""

    def __init__(self, client: OpenAICompatClient | None = None, template_version: str = "1.0.0"):
        self.client = client
        self.template = TEMPLATES[template_version]

    def synthesize(self, macro_snapshot: dict[str, Any], model: str | None = None) -> dict[str, Any]:
        """macro_snapshot → validated, linted WorldDoc (v1.0.0)."""
        if self.client is None:
            raise LLMUnavailableError(
                "seed-synth requires an OpenAI-compatible client (Ollama :11434 default); "
                "pass a stub in tests"
            )
        messages = self.template.messages(macro_snapshot)
        try:
            resp = self.client.chat(messages=messages, model=model, temperature=0.6, max_tokens=900)
        except httpx.HTTPError as e:  # connection/transport failures are "no LLM available"
            raise LLMUnavailableError(f"seed-synth LLM unreachable: {e}") from e
        try:
            payload = json.loads(resp.text)
        except json.JSONDecodeError as e:
            raise LLMUnavailableError(f"seed-synth: model returned non-JSON: {resp.text[:200]}") from e
        doc: dict[str, Any] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "prompt_version": self.template.version,
            "world_id": macro_snapshot.get("world_id", "world"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": resp.model,
            "macro_snapshot": {
                "as_of": macro_snapshot["as_of"],
                "series": macro_snapshot["series"],
            },
            "narrative": payload["narrative"],
            "inferred_risks": payload.get("inferred_risks", {}),
        }
        validate_world_doc(doc)
        issues = coherence_lint(doc)
        doc["coherence_issues"] = issues
        return doc