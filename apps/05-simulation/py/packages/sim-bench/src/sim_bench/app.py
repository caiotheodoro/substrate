"""simbench-runner service :8303."""

from __future__ import annotations

from fastapi import FastAPI

from sim_bench.runner import DEFAULT_SHOCK_IDS, BenchMatrixRunner


def get_datasets():
    from sim_datasets import get_dataset

    return {sid: get_dataset(sid) for sid in DEFAULT_SHOCK_IDS}


def get_matrix(n_members: int = 100):
    from sim_bench.adapters import default_adapters

    datasets = get_datasets()
    return BenchMatrixRunner(adapters=default_adapters(), datasets=datasets).run(n_members=n_members)


def create_app() -> FastAPI:
    app = FastAPI(title="simbench-runner", version="v1")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/run")
    def run(n_members: int = 100):
        frame = get_matrix(n_members)
        return frame.to_dict(orient="index")

    @app.get("/report")
    def report(n_members: int = 100):
        from sim_bench.report import build_report

        frame = get_matrix(n_members)
        return build_report(frame)

    return app


app = create_app()