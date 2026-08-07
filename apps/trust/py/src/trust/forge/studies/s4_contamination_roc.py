"""S4 — contamination monitor ROC: detection as a function of leak rate.

The leak probe fires when a task's value-level signature is in the leaked
knowledge base. As the leaked fraction grows, detection should rise; the
ROC-style curve (fire rate on leaked vs false-fire on clean) shows the
monitor's operating point. Blog angle: a contamination monitor you can
actually validate, not a dashboard.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trust.forge.contamination import ContaminationReport, monitor_contamination
from trust.forge.generators import DerivedArgTaskGenerator, ToolUseTaskGenerator
from trust.forge.study import write_json
from trust.forge.stratify import difficulty_match_splits
from trust.forge.difficulty import DifficultyModel
from trust.forge.calibration import SimulatedOracle


def run_all(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = ToolUseTaskGenerator().generate(n=200) + DerivedArgTaskGenerator().generate(n=30)
    oracle = SimulatedOracle()
    outcomes = [oracle.calibrate(t) for t in tasks]
    model = DifficultyModel().fit(tasks, outcomes)
    splits = difficulty_match_splits(tasks, model)

    results: dict[str, Any] = {}
    for leak_frac in (0.05, 0.1, 0.2, 0.3, 0.5):
        n_leaked = max(1, int(len(tasks) * leak_frac))
        leaked = {t.task_id for t in tasks[:n_leaked]}
        report = monitor_contamination(
            tasks,
            public=splits.public,
            private=splits.private,
            leaked_ids=leaked,
            corpus_texts=[],  # external corpus not relevant to the ROC
        )
        results[str(leak_frac)] = report.as_dict()
        print(f"leak {leak_frac:.0%}: fire-on-leaked {results[str(leak_frac)]['leak_probe_fire_rate_on_leaked']:.3f} "
              f"false-fire {results[str(leak_frac)]['leak_probe_false_fire_on_clean']:.4f}")

    write_json(out_dir / "s4-contamination-roc.json", results)
    return results


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/validation/studies")
    run_all(Path(p.parse_args().out))
    sys.exit(0)
