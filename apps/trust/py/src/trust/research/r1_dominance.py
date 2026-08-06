"""A-T-34 r1-dominance — evidence-based scoring vs self-report under shift.

Design (difficulty-controlled): the ConfBench generative model ties
correctness to a latent ``v`` and difficulty ``d``; evidence features are
noisy monotone encodings of both, while the self-report channel sees only
``v`` — a model cannot report uncertainty about difficulty it cannot
perceive. Under shift the workload gets harder and self-report inflates on
exactly those tasks.

The evidence scorer is the real TrustScorer (LightGBM + netcal calibration,
A-T-18) trained on the ConfBench training split; baselines are calibrated on
the base-eval split (the "at equal calibration" fairness condition), then
both are evaluated on base and shifted. Prediction: evidence retains
calibration and escalation ranking utility under shift; self-report
collapses.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trust.confbench.baselines import all_baselines
from trust.confbench.metrics import ScorerEval, evaluate_scorer, reliability_diagram
from trust.confbench.runner import run_confbench
from trust.confbench.tasks import ConfBenchTask, to_training_frame
from trust.scorer.train import train_scorer


def _evidence_scorer_factory(train: list[ConfBenchTask], _base: list[ConfBenchTask]):
    features, labels = to_training_frame(train)
    trained = train_scorer(features, labels, cv_folds=3, seed=42, model_version="r1")

    def scores(tasks: list[ConfBenchTask]) -> list[float]:
        return [trained.score(t.evidence.to_row()) for t in tasks]

    return scores


def run_r1(tasks: dict[str, list[ConfBenchTask]] | None = None, out_dir: str | Path | None = None) -> dict[str, Any]:
    """Run r1 and (optionally) write JSON + reliability PNGs to out_dir.

    Returns the full result dict with the dominance numbers."""
    from trust.confbench.tasks import load_confbench_tasks

    tasks = tasks or load_confbench_tasks()
    result = run_confbench(tasks, _evidence_scorer_factory, calibrate_baselines=True)
    summary = {
        "question": "At equal base calibration, does evidence-based confidence retain calibration and escalation utility under shift while self-report collapses?",
        "brier_base": {
            "evidence": result.evidence["base"].brier,
            **{k: result.baselines[k].brier for k in ("logprob_norm", "self_consistency", "verbalized")},
        },
        "brier_shifted": {
            "evidence": result.evidence["shifted"].brier,
            "logprob_norm": result.baselines["logprob_norm-shifted"].brier,
            "self_consistency": result.baselines["self_consistency-shifted"].brier,
            "verbalized": result.baselines["verbalized-shifted"].brier,
        },
        "ece_base": {
            "evidence": result.evidence["base"].ece,
            **{k: result.baselines[k].ece for k in ("logprob_norm", "self_consistency", "verbalized")},
        },
        "ece_shifted": {
            "evidence": result.evidence["shifted"].ece,
            "logprob_norm": result.baselines["logprob_norm-shifted"].ece,
            "self_consistency": result.baselines["self_consistency-shifted"].ece,
            "verbalized": result.baselines["verbalized-shifted"].ece,
        },
        "ndcg_escalation_shifted": {
            "evidence": result.evidence["shifted"].ndcg_escalation,
            "logprob_norm": result.baselines["logprob_norm-shifted"].ndcg_escalation,
            "self_consistency": result.baselines["self_consistency-shifted"].ndcg_escalation,
            "verbalized": result.baselines["verbalized-shifted"].ndcg_escalation,
        },
        "shift_delta": result.shift,
        "dominance": _dominance_summary(result),
    }
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "r1_dominance.json").write_text(json.dumps(summary, indent=2))
        evs = [
            result.evidence["base"],
            result.baselines["logprob_norm-shifted"],
            result.baselines["self_consistency-shifted"],
            result.baselines["verbalized-shifted"],
            result.evidence["shifted"],
        ]
        reliability_diagram(evs, str(out / "r1_reliability.png"))
        _shift_curve(tasks, str(out / "r1_shift_curve.png"))
    return summary


def _dominance_summary(result: Any) -> dict[str, bool]:
    return {
        "evidence_beats_best_baseline_brier_shifted": result.evidence["shifted"].brier
        < min(result.baselines[k].brier for k in ("logprob_norm-shifted", "self_consistency-shifted", "verbalized-shifted")),
        "evidence_beats_best_baseline_ece_shifted": result.evidence["shifted"].ece
        < min(result.baselines[k].ece for k in ("logprob_norm-shifted", "self_consistency-shifted", "verbalized-shifted")),
        "evidence_beats_best_baseline_ndcg_shifted": result.evidence["shifted"].ndcg_escalation
        > max(result.baselines[k].ndcg_escalation for k in ("logprob_norm-shifted", "self_consistency-shifted", "verbalized-shifted")),
    }


def _shift_curve(tasks: dict[str, list[ConfBenchTask]], path: str) -> bool:
    """Brier vs shift strength for evidence and the best baseline (self-report
    verbalized), sweeping difficulty+inflation."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    from trust.confbench.shift_generator import apply_shift, ShiftSpec

    scorer = _evidence_scorer_factory(tasks["train"], tasks["base_eval"])
    from trust.confbench.baselines import VerbalizedBaseline

    verbalized = VerbalizedBaseline()
    amounts = [0.0, 0.15, 0.3, 0.45]
    ev_brier, sr_brier = [], []
    for a in amounts:
        split = tasks["base_eval"]
        if a > 0:
            split = apply_shift(split, ShiftSpec(difficulty_shift=a), seed=int(a * 100))
        outcomes = [t.outcome for t in split]
        ev_brier.append(evaluate_scorer("evidence", scorer(split), outcomes).brier)
        sr_brier.append(evaluate_scorer("verbalized", verbalized.scores(split), outcomes).brier)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(amounts, ev_brier, marker="o", label="evidence")
    ax.plot(amounts, sr_brier, marker="o", label="self-report (verbalized)")
    ax.set_xlabel("difficulty shift")
    ax.set_ylabel("Brier")
    ax.set_title("r1 — Brier under shift")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return True


def _cli_main() -> None:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="trust-r1", description="A-T-34: evidence vs self-report under shift")
    parser.add_argument("--out", default="docs/validation", help="output dir for JSON + PNG artifacts (repo root docs/validation)")
    args = parser.parse_args()
    summary = run_r1(out_dir=args.out)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    _cli_main()
