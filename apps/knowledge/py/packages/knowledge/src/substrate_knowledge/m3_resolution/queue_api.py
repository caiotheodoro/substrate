"""A-K-14 human-confirmation-queue service — svc :8202.

Minimal FastAPI + HTML UI: list pending merge candidates, resolve
merge/split/skip, audit trail. Offline: in-memory store unless
`KNOW_BACKEND=pg`.
"""

from __future__ import annotations

import os
from html import escape

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from substrate_knowledge.core.storage import InMemoryStore, PostgresStore, Store
from substrate_knowledge.m3_resolution.human_queue import HumanConfirmationQueue, Resolution


def _store() -> Store:
    if os.environ.get("KNOW_BACKEND") == "pg":
        dsn = os.environ.get("POSTGRES_DSN") or "postgresql://substrate:substrate@localhost:5432/substrate"
        return PostgresStore(dsn)
    return InMemoryStore()


class ResolveBody(BaseModel):
    resolution: Resolution
    audited_by: str = "human"


def build_app(queue: HumanConfirmationQueue | None = None) -> FastAPI:
    q = queue or HumanConfirmationQueue(_store())

    app = FastAPI(title="human-confirmation-queue", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "human-queue", "port": 8202}

    @app.get("/queue")
    def list_queue() -> list[dict]:
        return [item.to_dict() for item in q.pending()]

    @app.get("/")
    def ui() -> str:
        rows = []
        for item in q.pending():
            rows.append(
                "<tr>"
                f"<td>{escape(item.left.get('name', item.left.get('entity_id', '?')))}</td>"
                f"<td>{escape(item.right.get('name', item.right.get('entity_id', '?')))}</td>"
                f"<td>{item.score:.3f}</td>"
                f"<td>"
                f'<form method="post" action="/resolve/{item.id}" style="display:inline">'
                f'<input type="hidden" name="resolution" value="merge"><button type="submit">merge</button></form> '
                f'<form method="post" action="/resolve/{item.id}" style="display:inline">'
                f'<input type="hidden" name="resolution" value="split"><button type="submit">split</button></form> '
                f'<form method="post" action="/resolve/{item.id}" style="display:inline">'
                f'<input type="hidden" name="resolution" value="skip"><button type="submit">skip</button></form>'
                f"</td></tr>"
            )
        body = "".join(rows)
        return (
            "<html><head><title>knowledge human-confirmation queue</title></head><body>"
            f"<h1>Pending merge candidates ({q.queue_depth()})</h1>"
            f"<table border='1'><tr><th>left</th><th>right</th><th>score</th><th>action</th></tr>{body}</table>"
            f"<p><a href='/audit'>audit log</a></p></body></html>"
        )

    @app.post("/resolve/{item_id}")
    def resolve(item_id: str, body: ResolveBody) -> dict:
        try:
            return q.resolve(item_id, body.resolution, body.audited_by).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/resolve-form/{item_id}")
    def resolve_form(item_id: str, resolution: str = "skip") -> dict:
        if resolution not in ("merge", "split", "skip"):
            raise HTTPException(status_code=400, detail=f"bad resolution {resolution!r}")
        return q.resolve(item_id, resolution, "ui").to_dict()

    @app.get("/audit")
    def audit() -> list[dict]:
        return q.audit_log()

    return app


app = build_app()
