"""simbench CLI + :8303 service. Commands: `simbench run --matrix`,
`simbench serve`. Each run is recorded to the registry before execution."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simbench")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--matrix", action="store_true", help="run the 4-shock matrix to Parquet")
    run.add_argument("--out", default="out/bench.parquet", help="output parquet path")
    run.add_argument("--n-members", type=int, default=100)
    run.set_defaults(func=_cmd_run)

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8303)
    serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


def _cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("sim_bench.app:create_app", factory=True, host=args.host, port=args.port)
    return 0


def _build_matrix(n_members: int) -> pd.DataFrame:
    from sim_bench.runner import DEFAULT_SHOCK_IDS, BenchMatrixRunner
    from sim_datasets import get_dataset
    from sim_engine import discover_entrypoints, list_adapters, get_adapter

    discover_entrypoints()
    if not list_adapters():
        from sim_engine import register_adapter
        from sim_engine.swarm_demo import CascadeBehaviourAdapter

        register_adapter(CascadeBehaviourAdapter())
    datasets = {sid: get_dataset(sid) for sid in DEFAULT_SHOCK_IDS}
    adapters = {m: get_adapter(m) for m in list_adapters()}
    return BenchMatrixRunner(adapters=adapters, datasets=datasets).run(n_members=n_members)


def _cmd_run(args) -> int:
    frame = _build_matrix(args.n_members)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    print(f"bench matrix written to {out} ({len(frame)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())