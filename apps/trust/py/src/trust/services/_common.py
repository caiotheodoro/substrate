"""Shared bits for the per-port FastAPI services."""
from __future__ import annotations

from fastapi import FastAPI


def make_app(name: str, version: str = "1.0.0") -> FastAPI:
    app = FastAPI(title=f"trust-{name}", version=version, description=f"@substrate/trust {name}")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": name}

    return app


def run(app: FastAPI, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)
