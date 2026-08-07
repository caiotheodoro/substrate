"""P4 — calibrated split stratification.

The property that makes a leaderboard honest: public-split performance
predicts private-split performance because both share the difficulty
distribution. Splits are built by binning tasks on fitted difficulty and
allocating proportionally into each split (stratified sampling), so the
difficulty histograms match across splits.

``split_predictability`` is the acceptance test: fit per-split solve rates
and require a minimum rank correlation between splits on a synthetic
population of systems — a deliberately mis-stratified split must fail it.
``split_distribution_kl`` is a separate, uncombined diagnostic (not part of
the accept/reject decision) for eyeballing how well-matched the two
difficulty histograms are.
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
    n_bins: int = N_BINS,
) -> SplitSet:
    """Stratify tasks into public/private splits matched on fitted
    difficulty: bin by difficulty, then allocate proportionally per bin.
    Deterministic (seeded RNG). ``n_bins`` defaults to the module's N_BINS
    but is a real parameter — S5's nested-CV study tunes it, and a prior
    version had no way to actually pass a swept value in here (it only
    ever reached `split_predictability`'s own binning, the acceptance
    TEST's ruler, not the split construction itself)."""
    import random

    rng = random.Random(seed)
    binned: dict[int, list[ForgeTask]] = {i: [] for i in range(n_bins)}
    for t in tasks:
        d = model.difficulty(t)
        bin_idx = min(n_bins - 1, int(d * n_bins))
        binned[bin_idx].append(t)

    public: list[ForgeTask] = []
    private: list[ForgeTask] = []
    for bin_idx in range(n_bins):
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


def split_distribution_kl(
    public: list[ForgeTask], private: list[ForgeTask], model: DifficultyModel, *, eps: float = 1e-6
) -> float:
    """KL divergence between the two difficulty distributions — the
    matched-stratification quality metric. Near 0 = well matched.

    Skipping a term when ``pi == 0`` is mathematically correct (the limit
    of ``p*log(p/q)`` as ``p -> 0`` is 0). Skipping when ``qi == 0`` is
    NOT: a bin the public split occupies that the private split never
    touches is exactly the maximally-mismatched case KL is supposed to
    penalize heavily (the true divergence there is +inf), and a prior
    version silently dropped that term instead — an empty private split
    reported KL == 0.0 ("perfectly matched") rather than the highly
    mismatched result it actually is. ``eps`` floors ``qi`` instead of
    skipping, so a zero-mass bin contributes a large finite penalty."""
    import math as _math

    p = difficulty_distribution(public, model)
    q = difficulty_distribution(private, model)
    kl = 0.0
    for i in range(N_BINS):
        pi = p[i]
        if pi <= 0:
            continue
        qi = max(q[i], eps)
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
    """Split into exactly ``min(n_bins, len(values))`` near-equal-size
    consecutive chunks (the first ``n % k`` chunks absorb the remainder),
    and return each chunk's mean.

    Guaranteeing the EXACT chunk count (not "roughly n_bins depending on
    how a fixed width happens to divide this particular length") is the
    part that matters: two lists of different length, binned independently
    with the old width-based approach, could produce a different number of
    chunks each (e.g. len 10 and len 12 at n_bins=5 produced 5 and 4
    chunks) — `_spearman` requires equal-length inputs and silently
    returned 0.0 on any such mismatch, which reads as "public does not
    predict private" when the real failure was just a binning bug.
    """
    if not values:
        return []
    n = len(values)
    k = min(n_bins, n)
    base, extra = divmod(n, k)
    means: list[float] = []
    idx = 0
    for i in range(k):
        size = base + (1 if i < extra else 0)
        chunk = values[idx : idx + size]
        means.append(sum(chunk) / len(chunk))
        idx += size
    return means


def _bin_spearman(a: list[float], b: list[float], n_bins: int) -> float:
    """Spearman correlation between the per-bin mean solve rates of two
    aligned (same-difficulty-rank) rate lists. Splits may have different
    lengths — both are binned into the SAME chunk count
    (``min(n_bins, len(a), len(b))``) so `_bin_means`'s output is always
    comparable, regardless of how unevenly the two lengths divide."""
    if not a or not b:
        return 0.0
    k = min(n_bins, len(a), len(b))
    ba = _bin_means(a, k)
    bb = _bin_means(b, k)
    if len(ba) < 2 or len(bb) < 2:
        return 0.0
    return _spearman(ba, bb)


def _spearman(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    ra = _rank(a)
    rb = _rank(b)
    n = len(a)
    # Pearson correlation of the (average) rank vectors — the tie-correct
    # definition of Spearman's rho. The 1 - 6*sum(d^2)/(n(n^2-1)) shortcut
    # only equals this when ranks are an untied 1..n permutation; with
    # averaged ties (see _rank) it diverges from what scipy's
    # tie-corrected spearmanr reports (see trust.forge.study.spearman,
    # which has the same fix and a scipy cross-check test).
    mean_ra = sum(ra) / n
    mean_rb = sum(rb) / n
    cov = sum((ra[i] - mean_ra) * (rb[i] - mean_rb) for i in range(n))
    var_a = sum((x - mean_ra) ** 2 for x in ra)
    var_b = sum((x - mean_rb) ** 2 for x in rb)
    denom = (var_a * var_b) ** 0.5
    return cov / denom if denom else 0.0


def _rank(values: list[float]) -> list[float]:
    """Fractional (average) ranks — see study.spearman's rank() for why
    this matters (ties are common in this pipeline's actual outputs)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
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
