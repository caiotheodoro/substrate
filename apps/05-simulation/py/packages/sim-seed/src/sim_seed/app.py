"""seed-synth HTTP service on :8302 (A-S-20)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from sim_shared.llm import LLMConfig, LLMUnavailableError, OpenAICompatClient

from .schema import load_schema
from .synth import SeedSynthesizer

app = FastAPI(title="seed-synth", version="0.1.0")

_synthesizer: SeedSynthesizer | None = None


def get_synthesizer() -> SeedSynthesizer:
    global _synthesizer
    if _synthesizer is None:
        try:
            _synthesizer = SeedSynthesizer(client=OpenAICompatClient(config=LLMConfig()))
        except Exception:
            _synthesizer = SeedSynthesizer(client=None)
    return _synthesizer


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "seed-synth", "port": 8302}


@app.get("/schema")
def schema() -> dict:
    return load_schema()


@app.post("/synth")
def synth(snapshot: dict) -> dict:
    try:
        return get_synthesizer().synthesize(snapshot)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e