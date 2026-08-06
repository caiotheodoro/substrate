"""B2 — uncertainty decomposition: epistemic vs aleatoric (Airbnb Layer 1).

Dual indeterminacy (Abbasi Yadkori et al., cited in the article): noise in
LLM evaluation has two sources needing separate diagnosis.

- **Epistemic** — judge/model limits. A better judge resolves it. Fixable.
- **Aleatoric** — task ambiguity. No judge improvement resolves it.

Conflating them misclassifies high-entropy responses as hallucinations.
Operational split: sample-level judge variance is measured across a *ladder*
of judges (cheap → strong). Variance that persists at the top of the ladder
is aleatoric (the task is genuinely ambiguous); variance that collapses as
the judge improves is epistemic (the strong judge resolves it). Naive
methods that only look at one judge's high-entropy output cannot tell the
two apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from trust.confbench.noise_diagnostics import sample_hash

# Ladder semantics: judge_strength 0 = cheap stub, 1.0 = strongest available.
LADDER = (0.0, 0.5, 1.0)


@dataclass
class SampleDecomposition:
    sample_id: str
    scores_by_strength: dict[float, list[float]] = field(default_factory=dict)
    task_entropy: float = 0.0  # cross-judge disagreement at the strongest judge

    @property
    def variance_at_strongest(self) -> float:
        return _variance(self.scores_by_strength.get(max(self.scores_by_strength), []))


@dataclass
class UncertaintyReport:
    n_samples: int
    epistemic_fraction: float
    aleatoric_fraction: float
    aleatoric_samples: list[str] = field(default_factory=list)
    epistemic_samples: list[str] = field(default_factory=list)
    resolution: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_samples": self.n_samples,
            "epistemic_fraction": round(self.epistemic_fraction, 4),
            "aleatoric_fraction": round(self.aleatoric_fraction, 4),
            "n_aleatoric": len(self.aleatoric_samples),
            "n_epistemic": len(self.epistemic_samples),
            "resolution": {str(k): round(v, 4) for k, v in self.resolution.items()},
        }

    def write(self, path: str | Path) -> None:
        import json

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.as_dict(), indent=2))


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def _mean(values: Any) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0

def decompose_uncertainty(
    sample_ids: list[str],
    judge_family: Callable[[float, str], Callable[[str], float]],
    *,
    samples_per_judge: int = 5,
    ladder: tuple[float, ...] = LADDER,
    variance_threshold: float = 0.01,
) -> UncertaintyReport:
    """Decompose per-sample judge variance across a judge ladder.

    ``judge_family(strength, sample_id)`` returns a callable producing one
    score draw for that (strength, sample). Each sample is scored
    ``samples_per_judge`` times at every ladder strength.

    Decomposition rule (operationalized dual indeterminacy):
      - variance at the STRONGEST judge above threshold → aleatoric (task
        ambiguity no judge resolves);
      - variance only at weaker judges (resolved by the strong one) →
        epistemic (judge limit, fixable);
      - otherwise stable → confident.
    """
    decompositions: list[SampleDecomposition] = []
    for sid in sample_ids:
        by_strength: dict[float, list[float]] = {}
        for strength in ladder:
            judge = judge_family(strength, sid)
            by_strength[strength] = [float(judge()) for _ in range(samples_per_judge)]
        decompositions.append(SampleDecomposition(sample_id=sid, scores_by_strength=by_strength))

    aleatoric: list[str] = []
    epistemic: list[str] = []
    # resolution curve: mean variance at each ladder strength — the strong
    # judge's variance floor is the aleatoric baseline
    resolution = {
        strength: _mean(_variance(d.scores_by_strength[strength]) for d in decompositions) for strength in ladder
    }

    for d in decompositions:
        var_weak = _variance(d.scores_by_strength[ladder[0]])
        var_strong = d.variance_at_strongest
        if var_strong >= variance_threshold:
            aleatoric.append(d.sample_id)
        elif var_weak >= variance_threshold:
            epistemic.append(d.sample_id)

    n = len(decompositions)
    return UncertaintyReport(
        n_samples=n,
        epistemic_fraction=len(epistemic) / n if n else 0.0,
        aleatoric_fraction=len(aleatoric) / n if n else 0.0,
        aleatoric_samples=aleatoric,
        epistemic_samples=epistemic,
        resolution=resolution,
    )


def naive_high_entropy_flags(
    sample_ids: list[str],
    judge: Callable[[str], float],
    *,
    samples: int = 5,
    entropy_threshold: float = 0.01,
) -> list[str]:
    """The naive baseline the article warns about: a single judge's
    high-entropy outputs are flagged without separating the source — this
    misclassifies aleatoric (task) AND epistemic (judge) samples the same
    way. B2 exists to show the separation the naive method cannot."""
    flagged: list[str] = []
    for sid in sample_ids:
        draws = [float(judge(sid)) for _ in range(samples)]
        if _variance(draws) >= entropy_threshold:
            flagged.append(sid)
    return flagged
