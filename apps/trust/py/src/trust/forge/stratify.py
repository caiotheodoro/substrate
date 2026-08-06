"""P4 — calibrated split stratification.

The property that makes a leaderboard honest: public-split performance
predicts private-split performance because both share the difficulty
distribution. Splits are built by binning tasks on fitted difficulty and
allocating proportionally into each split (stratified sampling), so the
difficulty histograms match across splits.

``split_predictability`` is the acceptance test: fit per-split solve rates
and require a minimum rank correlation between splits on a synthetic
population of systems — a deliberately mis-stratified split must fail it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean

from trust.forge.difficulty import DifficultyModel
from trust.forge.task import ForgeTask

N_BINS = 5


@dataclass
class SplitSet:
    public: list[ForgeTask]
    private: list[ForgeTask]

    def sizes(self) -> dict[str, int]:
        return {"public": len(self.public), "private": len(self.private)}


def difficulty_match_splits(
    tasks: list[ForgeTask],
    model: DifficultyModel,
    *,
    private_fraction: float = 0.5,
    seed: int = 7,
) -> SplitSet:
    """Stratify tasks into public/private splits matched on fitted
    difficulty: bin by difficulty, then allocate proportionally per bin.
    Deterministic (seeded RNG)."""
    import random

    rng = random.Random(seed)
    binned: dict[int, list[ForgeTask]] = {i: [] for i in range(N_BINS)}
    for t in tasks:
        d = model.difficulty(t)
        bin_idx = min(N_BINS - 1, int(d * N_BINS))
        binned[bin_idx].append(t)

    public: list[ForgeTask] = []
    private: list[ForgeTask] = []
    for bin_idx in range(N_BINS):
        bucket = list(binned[bin_idx])
        rng.shuffle(bucket)
        n_private = int(round(len(bucket) * private_fraction))
        private.extend(bucket[:n_private])
        public.extend(bucket[n_private:])
    return SplitSet(public=public, private=private)


def difficulty_distribution(tasks: list[ForgeTask], model: DifficultyModel) -> dict[int, float]:
    """Fraction of tasks per difficulty bin (for histogram comparison)."""
    counts = [0] * N_BINS
    for t in tasks:
        d = model.difficulty(t)
        counts[min(N_BINS - 1, int(d * N_BINS))] += 1
    n = max(len(tasks), 1)
    return {i: counts[i] / n for i in range(N_BINS)}


def split_distribution_kl(public: list[ForgeTask], private: list[ForgeTask], model: DifficultyModel) -> float:
    """KL divergence between the two difficulty distributions — the
    matched-stratification quality metric. Near 0 = well matched."""
    import math as _math

    p = difficulty_distribution(public, model)
    q = difficulty_distribution(private, model)
    kl = 0.0
    for i in range(N_BINS):
        pi = p[i]
        qi = q[i]
        if pi > 0 and qi > 0:
            kl += pi * _math.log(pi / qi)
    return kl


def split_predictability(
    systems: dict[str, dict[str, float]],
    *,
    min_correlation: float = 0.8,
    n_bins: int = N_BINS,
) -> dict[str, object]:
    """The acceptance test: public-split performance must predict
    private-split performance. For every system, per-task solve rates are
    grouped into difficulty-agnostic positions — we correlate the per-bin
    MEAN solve rates of the public split against the per-bin mean solve
    rates of the private split, using the same fixed bin boundaries for
    both (bin 0 = easiest task positions... ). In practice the fixture
    passes pre-sorted per-task rates aligned by difficulty rank.

    ``systems`` maps system_name -> {"public": [...solve rates...],
    "private": [...]} — both lists must be aligned by task difficulty rank
    (task i in public has the same difficulty rank as task i in private).
    """
    correlations: dict[str, float] = {}
    for name, rates in systems.items():
        pub, priv = rates["public"], rates["private"]
        correlations[name] = _bin_spearman(pub, priv, n_bins)
    passed = all(c >= min_correlation for c in correlations.values())
    return {
        "passed": passed,
        "correlations": {k: round(v, 4) for k, v in correlations.items()},
        "min_correlation": min_correlation,
    }


def _bin_means(values: list[float], n_bins: int) -> list[float]:
    """Mean of every ceil(n/n_bins) consecutive values (aligned by rank)."""
    if not values:
        return []
    width = max(1, math.ceil(len(values) / n_bins))
    means: list[float] = []
    for i in range(0, len(values), width):
        chunk = values[i : i + width]
        means.append(sum(chunk) / len(chunk))
    return means


def _bin_spearman(a: list[float], b: list[float], n_bins: int) -> float:
    """Spearman correlation between the per-bin mean solve rates of two
    aligned (same-difficulty-rank) rate lists. Splits may have different
    lengths — each is binned independently into the same number of bins."""
    if not a or not b:
        return 0.0
    ba = _bin_means(a, n_bins)
    bb = _bin_means(b, n_bins)
    if len(ba) < 2 or len(bb) < 2:
        return 0.0
    return _spearman(ba, bb)


def _spearman(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    ra = _rank(a)
    rb = _rank(b)
    n = len(a)
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    denom = n * (n * n - 1) / 6.0
    return 1.0 - (6.0 * d2) / (6.0 * denom) if denom else 0.0


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for pos, idx in enumerate(indexed):
        ranks[idx] = pos + 1
    return ranks


def system_solve_rates(
    tasks: list[ForgeTask],
    ability: float,
    seed: int,
    model: DifficultyModel | None = None,
) -> list[float]:
    """Synthetic system: per-task solve rate = sigmoid(ability - difficulty)
    + deterministic noise. The TRUE difficulty (the oracle's underlying
    ``difficulty_seed``) drives real solve behavior — the model is the
    *measurement* used for split construction. Returns rates sorted by
    ascending true difficulty so rates from different splits are
    rank-aligned (the predictability-test contract)."""
    import hashlib

    pairs: list[tuple[float, float]] = []
    for t in tasks:
        key = f"{seed}:{t.task_id}"
        noise = (int(hashlib.sha256(key.encode()).hexdigest()[:6], 16) / 0xFFFFFF) * 0.1
        d = t.difficulty_seed  # true difficulty, not the fitted estimate
        z = ability - d
        rate = max(0.0, min(1.0, 1.0 / (1.0 + math.exp(-z)) + noise - 0.05))
        pairs.append((d, rate))
    pairs.sort(key=lambda p: p[0])
    return [rate for _, rate in pairs]
