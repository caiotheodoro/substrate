"""A-K-02 characterization-decision-api — svc :8201.

POST /characterize {docs} -> architecture recommendation (vector /
vector+graph / graph-only) or an opinionated refusal when the corpus is too
small to characterize. The decision rule is pure (decision.py); this module
is the HTTP shell.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from substrate_knowledge.m1_characterization.decision import DecisionRule
from substrate_knowledge.m1_characterization.profiler import CorpusDocument, CorpusStructuralProfiler


class CharacterizeRequest(BaseModel):
    docs: list[dict] = Field(min_length=1)


class CharacterizeResponse(BaseModel):
    verdict: dict


def build_characterize_app(rule: DecisionRule | None = None) -> FastAPI:
    decision_rule = rule or DecisionRule()

    app = FastAPI(title="characterization-decision-api", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "characterize", "port": 8201}

    @app.post("/characterize", response_model=CharacterizeResponse)
    def characterize(req: CharacterizeRequest) -> CharacterizeResponse:
        docs = [
            CorpusDocument(
                doc_id=d.get("doc_id", f"doc-{i}"),
                text=d.get("text", ""),
                source=d.get("source", "unknown"),
                ts=d.get("ts"),
            )
            for i, d in enumerate(req.docs)
        ]
        profile = CorpusStructuralProfiler().profile(docs)
        verdict = decision_rule.decide(profile)
        return CharacterizeResponse(verdict=verdict.to_dict())

    return app


app = build_characterize_app()
