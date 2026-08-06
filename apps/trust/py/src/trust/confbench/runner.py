"""A-T-08 confbench-runner — score-level Brier/ECE, NDCG-escalation and
shift-delta over the ConfBench task splits, for the evidence scorer and the
banned baselines.

The evidence scorer is trained on the ConfBench training split (whose ids are
holdout-disjoint from evaluation, A-T-10), calibrated on out-of-fold
predictions, then evaluated on base and shifted distributions. Baselines read
the self-report channel directly (calibrated on the base split when
``calibrate_baselines`` is set — the "at equal calibration" fairness
condition of R1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from trust.confbench.baselines import BaselineScorer, all_baselines
from trust.confbench.eval_cache import EvalCache, cache_baseline_scores
from trust.confbench.holdout import HoldoutSet
from trust.confbench.metrics import ScorerEval, evaluate_scorer, reliability_diagram
from trust.confbench.tasks import ConfBenchTask

EvidenceScorerFactory = Callable[[list[ConfBenchTask], list[ConfBenchTask]], Callable[[list[ConfBenchTask]], list[float]]]
"""Factory: (train_tasks, base_eval_tasks) -> scores(tasks) -> list[float].

Kept a factory so the runner does not import the scorer package (the
r1 experiment wires the real TrustScorer through it).
"""


@dataclass
class ConfBenchResult:
    """Full runner output — serializable for docs/validation/."""

    evidence: dict[str, ScorerEval]
    baselines: dict[str, ScorerEval]
    shift: dict[str, dict[str, float]]
    holdout: HoldoutSet
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence": {k: v.as_dict() for k, v in self.evidence.items()},
            "baselines": {k: v.as_dict() for k, v in self.baselines.items()},
            "shift": self.shift,
            "holdout_size": len(self.holdout.task_ids),
            "metadata": self.metadata,
        }

    def write(self, out_dir: Path) -> list[str]:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "confbench_report.json").write_text(json.dumps(self.as_dict(), indent=2))
        paths = ["confbench_report.json"]
        evs = [self.evidence["base"], *[self.baselines[k] for k in ("logprob_norm", "self_consistency", "verbalized")]]
        paths.append("confbench_reliability.png")
        reliability_diagram(evs, str(out_dir / "confbench_reliability.png"))
        return paths


def run_confbench(
    tasks: dict[str, list[ConfBenchTask]],
    scorer_factory: EvidenceScorerFactory,
    holdout: HoldoutSet | None = None,
    baselines: list[BaselineScorer] | None = None,
    calibrate_baselines: bool = True,
    seed: int = 42,
    cache: EvalCache | None = None,
) -> ConfBenchResult:
    """Run the full ConfBench cycle: train → eval on base → eval on shift.

    Fairness (R1's "at equal calibration"): the evidence scorer trains on the
    training split; each baseline's calibrator is fit on the *same* training
    split's (self-report, outcome) pairs. Both are then evaluated on the
    base and shifted splits — out-of-sample for both.

    ``cache`` (A2): when provided, baseline scores are memoized per
    (baseline, task_id) — identical reruns are served from cache and a
    run interrupted midway resumes without recomputing finished samples.
    """
    train, base_eval, shifted_eval = tasks["train"], tasks["base_eval"], tasks["shifted_eval"]
    holdout = holdout or HoldoutSet()
    leaked = [t.task_id for t in train if holdout.is_holdout(t.task_id)]
    if leaked:
        raise ValueError(f"A-T-10 holdout discipline violated: {len(leaked)} train tasks are holdout members")
    scorer = scorer_factory(train, base_eval)
    baselines = baselines or all_baselines()

    evidence: dict[str, ScorerEval] = {}
    for split_name, split in (("base", base_eval), ("shifted", shifted_eval)):
        conf = scorer(split)
        outcomes = [t.outcome for t in split]
        evidence[split_name] = evaluate_scorer("evidence", conf, outcomes)
        evidence[split_name].name = f"evidence-{split_name}"

    base_outcomes = [t.outcome for t in base_eval]
    shifted_outcomes = [t.outcome for t in shifted_eval]
    shift = _compute_shift(evidence["base"], evidence["shifted"])

    train_outcomes = [t.outcome for t in train]
    baseline_evals: dict[str, ScorerEval] = {}
    for bl in baselines:
        if cache is not None:
            train_conf = cache_baseline_scores(cache, bl.name, [t.task_id for t in train], lambda: bl.scores(train))
            base_conf = cache_baseline_scores(cache, bl.name, [t.task_id for t in base_eval], lambda: bl.scores(base_eval))
            shifted_conf = cache_baseline_scores(cache, bl.name, [t.task_id for t in shifted_eval], lambda: bl.scores(shifted_eval))
        else:
            train_conf = bl.scores(train)
            base_conf = bl.scores(base_eval)
            shifted_conf = bl.scores(shifted_eval)
        if calibrate_baselines:
            cal = _calibrate_on_base(train_conf, train_outcomes, seed)
            base_conf = [cal.predict([c])[0] for c in base_conf]
            shifted_conf = [cal.predict([c])[0] for c in shifted_conf]
        baseline_evals[bl.name] = evaluate_scorer(bl.name, base_conf, base_outcomes, banned=True)
        baseline_evals[bl.name].name = f"{bl.name}-base"
        shifted_ev = evaluate_scorer(bl.name, shifted_conf, shifted_outcomes, banned=True)
        shifted_ev.name = f"{bl.name}-shifted"
        baseline_evals[f"{bl.name}-shifted"] = shifted_ev

    return ConfBenchResult(
        evidence=evidence,
        baselines=baseline_evals,
        shift=shift,
        holdout=holdout,
        metadata={
            "seed": seed,
            "n_train": len(train),
            "n_base": len(base_eval),
            "n_shifted": len(shifted_eval),
            "cache": cache.stats() if cache is not None else None,
        },
    )


def _compute_shift(base: ScorerEval, shifted: ScorerEval) -> dict[str, dict[str, float]]:
    return {
        "brier_delta": round(shifted.brier - base.brier, 6),
        "ece_delta": round(shifted.ece - base.ece, 6),
        "ndcg_delta": round(shifted.ndcg_escalation - base.ndcg_escalation, 6),
        "brier_base": round(base.brier, 6),
        "brier_shifted": round(shifted.brier, 6),
        "ece_base": round(base.ece, 6),
        "ece_shifted": round(shifted.ece, 6),
    }


def _calibrate_on_base(confidence: list[float], base_outcomes: list[bool], seed: int):
    """Isotonic calibration of a raw channel on the training split (the same
    data the evidence scorer trains on) — the R1 fairness condition."""
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(confidence, [1.0 if y else 0.0 for y in base_outcomes])
    return iso
