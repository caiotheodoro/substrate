"""A-S-13 — sim-api :8300.

Endpoints:
  GET /health
  GET /scenarios                — the 4 shock scenarios + holdout flag
  GET /scenarios/{scenario_id}  — one scenario
  POST /injections/{scenario_id}/replay — apply the C6 injection to a
        synthetic world; returns the replay frames + world events + run_id
        (persisted to sim-db)
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from sim_cross.db import SimDB
from sim_injection import InjectionRuntime, build_shock_seed, get_scenario
from sim_injection.spec import InjectionSpec
from sim_engine.world import Sector, World


def _build_world(seed: int) -> World:
    world = World()
    world.add_macro("rates", 0.0)
    _ = seed
    for name in ("goods", "labor", "transport", "finance"):
        world.add_sector(Sector(name=name))
    return world


def _replay_spec(scenario_id: str, window: str, steps: int) -> InjectionSpec:
    return InjectionSpec.from_dict(
        {
            "id": f"replay-{scenario_id}",
            "profile": "trade-policy shock",
            "magnitude": 0.15,
            "channels": ["goods-demand"],
            "ramp": "linear",
            "horizon": steps,
            "start": (window.split("/")[0] + "-01") if "-" not in window.split("/")[0] else window.split("/")[0],
        }
    )


def create_app(db: SimDB | None = None) -> FastAPI:
    db = db or SimDB()
    app = FastAPI(title="sim-api", version="v1")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    def _scenario_doc(s) -> dict:
        return {
            "id": s.id,
            "name": s.name,
            "window": s.window,
            "series": list(s.series),
            "holdout": s.is_holdout,
            "seed": s.seed,
            "realizedOutcome": s.realizedOutcome,
        }

    @app.get("/scenarios")
    def scenarios() -> list[dict]:
        from sim_injection import list_scenarios

        return [_scenario_doc(get_scenario(sid)) for sid in list_scenarios()]

    @app.get("/scenarios/{scenario_id}")
    def one_scenario(scenario_id: str) -> dict:
        try:
            return _scenario_doc(get_scenario(scenario_id))
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown scenario: {scenario_id}")

    @app.post("/injections/{scenario_id}/replay")
    def replay(scenario_id: str, steps: int = 12) -> dict:
        try:
            scenario = get_scenario(scenario_id)
            world_seed = build_shock_seed(scenario.id, allow_scoring=True)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown scenario: {scenario_id}")

        world = _build_world(int(world_seed["seed"]))
        spec = _replay_spec(scenario.id, scenario.window, steps)
        runtime = InjectionRuntime(world, spec)
        frames = list(runtime.replay(steps))
        run_id = f"replay-{scenario.id}"
        db.add_run(run_id, scenario.id, "injection-replay", int(world_seed["seed"]), str(world_seed["as_of"]))
        seq = 0
        for ev in world.events.drain():
            payload = dict(ev.payload)
            db.add_event(run_id, seq, ev.kind, "WORLD", payload)
            seq += 1
        return {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "holdout": scenario.is_holdout,
            "seed": int(world_seed["seed"]),
            "as_of": str(world_seed["as_of"]),
            "frames": [
                {"t": f.t, "multiplier": round(f.multiplier, 4), "world": f.world_snapshot}
                for f in frames
            ],
            "events": db.events_df(run_id).to_dict(orient="records"),
        }

    return app


def make_spec(scenario_id: str, steps: int) -> InjectionSpec:
    """Spec used by /replay (kept importable for tests)."""
    return _replay_spec(scenario_id, "2020-03/2020-06", steps)


app = create_app()