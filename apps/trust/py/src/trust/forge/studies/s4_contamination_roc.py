"""S4 — contamination monitor ROC: detection as a function of leak rate.

The leak probe fires when a task's value-level signature is in an
INDEPENDENTLY-BUILT knowledge base (see contamination.build_reference_corpus)
— not one derived from the same task population being tested, which would
make "fire on leaked" trivially guaranteed by construction rather than a
measured detection event. As the leaked fraction grows, detection should
rise; the ROC-style curve (fire rate on leaked vs false-fire on clean) shows
the monitor's operating point. Blog angle: a contamination monitor you can
actually validate, not a dashboard.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trust.forge.contamination import (
    ContaminationReport,
    build_reference_corpus,
    inject_leaks,
    leaked_knowledge_base,
    monitor_contamination,
)
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

    reference_corpus = build_reference_corpus(len(tasks))
    kb = leaked_knowledge_base(reference_corpus)

    results: dict[str, Any] = {}
    for leak_frac in (0.05, 0.1, 0.2, 0.3, 0.5):
        contam_tasks, leaked_ids = inject_leaks(tasks, reference_corpus, fraction=leak_frac, seed=7)
        report = monitor_contamination(
            contam_tasks,
            public=splits.public,
            private=splits.private,
            knowledge_base=kb,
            leaked_ids=leaked_ids,
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
