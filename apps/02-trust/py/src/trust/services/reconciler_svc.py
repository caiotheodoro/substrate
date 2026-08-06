"""A-T-31 :8040 outcome-reconciler — C2 rows → pending/confirmed/delayed/conflicting."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from trust.contracts import DecisionRecord
from trust.recalib.reconciler import OutcomeReconciler, Reconciliation
from trust.services._common import make_app, run

PORT = 8040


class DecisionModel(BaseModel):
    decisionId: str
    turnId: str
    action: str
    confidenceFeatures: dict[str, Any] = {}
    verdict: str = "escalate"
    outcome: Optional[bool] = None
    confirmedAt: Optional[str] = None


def create_app(reconciler: OutcomeReconciler | None = None) -> FastAPI:
    reconciler = reconciler or OutcomeReconciler()
    app = make_app("outcome-reconciler")

    @app.post("/reconcile")
    def reconcile(req: DecisionModel) -> dict[str, object]:
        record = DecisionRecord(
            decisionId=req.decisionId,
            turnId=req.turnId,
            action=req.action,
            confidenceFeatures=req.confidenceFeatures,
            verdict=req.verdict,  # type: ignore[arg-type]
            outcome=req.outcome,
            confirmedAt=req.confirmedAt,
        )
        state = reconciler.reconcile(record)
        return state.as_dict()

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
