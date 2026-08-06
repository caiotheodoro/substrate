"""A-S-34 — CLI harness for the believability probes.

Runs A-S-31 behavioral probes + A-S-33 calibration corpus into a probe
report (JSON), using a small bundled synthetic room transcript by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sim_probes import CalibrationCorpus, ProbeReport, _demo_events, run_all_probes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sim-probes")
    parser.add_argument("--events", help="JSONL of C1 events (kind,payload.agent,t); default: bundled fixture")
    parser.add_argument("--rounds", type=int, default=48, help="total rounds for the lurking denominator")
    parser.add_argument("--out", default="out/probe-report.json")
    args = parser.parse_args(argv)

    if args.events:
        import json

        events = [json.loads(line) for line in Path(args.events).read_text().splitlines() if line.strip()]
    else:
        events = _demo_events(args.rounds)

    report = ProbeReport(run_all_probes(events, total_rounds=args.rounds), corpus=CalibrationCorpus())
    path = report.write(Path(args.out))
    passed = sum(1 for p in report.probes if p.passed)
    print(f"probe report written to {path} — {passed}/{len(report.probes)} probes within bounds")
    return 0 if passed == len(report.probes) else 1


if __name__ == "__main__":
    sys.exit(main())