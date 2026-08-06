"""A-T-32 :8041 recalibration-scheduler — trigger scorer-train over HTTP.

The real scheduling is APScheduler inside ``RecalibrationScheduler``; the
service exposes the same trigger so 01/ops can fire it on demand."""
from __future__ import annotations

from fastapi import FastAPI

from trust.services._common import make_app, run

PORT = 8041


def create_app(trigger=None) -> FastAPI:
    app = make_app("recalibration-scheduler")

    @app.post("/trigger")
    def trigger_retrain() -> dict:
        if trigger is None:
            return {"status": "no-op", "reason": "no trigger wired in this process"}
        report = trigger()
        return report.as_dict()

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
