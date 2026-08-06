"""Micro-adapter two-gate loop (Airbnb Layer 3 — evolve of r5/gated-data).

A micro adapter is a small correction patch (LoRA rank < 50 in their world;
here: a scored candidate) that ships like a software hotfix: scoped to ONE
issue, validated behind TWO gates before canary deployment, with lifecycle
rules (fuse co-triggering patches / retrain on accumulation / unload unused)
tracked for the research program.

The two gates, mapped onto our stack:

1. **No-regression gate** — the patch must not regress expert-reviewed
   domains. We evaluate the candidate on a golden domain set (the ConfBench
   holdout / labeled golden slices) and require per-domain accuracy to stay
   at or above the incumbent's.
2. **Uncertainty gate** — high-uncertainty outputs (judge variance above
   threshold, per B2) are flagged for human review instead of shipping.

Canary semantics: a passing patch is released to a canary lane (the budget
gate / escalation band in 01), where an anomaly rolls it back. Lifecycle
counters (co-trigger counts, patch count per category, last-triggered) feed
the RFC rules: fuse co-triggering patches, retrain on accumulation, unload
unused patches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from trust.confbench.metrics import ScorerEval, evaluate_scorer
from trust.gated_data.models import Dataset

# The empirical ceiling (Pletenev et al., cited in the article): patches
# against one category beyond this should be folded into a clean retrain.
MAX_PATCHES_PER_CATEGORY = 200


@dataclass
class DomainEval:
    """Per-domain accuracy of a candidate vs the incumbent (no-regression gate)."""

    domain: str
    incumbent_accuracy: float
    candidate_accuracy: float

    @property
    def regressed(self) -> bool:
        return self.candidate_accuracy < self.incumbent_accuracy - 1e-9


@dataclass
class NoRegressionResult:
    domains: list[DomainEval] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(d.regressed for d in self.domains)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "domains": [
                {"domain": d.domain, "incumbent": round(d.incumbent_accuracy, 4), "candidate": round(d.candidate_accuracy, 4)}
                for d in self.domains
            ],
        }


@dataclass
class UncertaintyFlag:
    sample_id: str
    variance: float
    threshold: float
    action: str = "human-review"

    def as_dict(self) -> dict[str, Any]:
        return {"sample_id": self.sample_id, "variance": round(self.variance, 4), "action": self.action}


@dataclass
class MicroPatchVerdict:
    patch_id: str
    issue: str
    category: str
    no_regression: NoRegressionResult
    uncertainty_flags: list[UncertaintyFlag] = field(default_factory=list)
    shipped: bool = False
    canary_lane: str | None = None
    decided_at: str = ""

    @property
    def flagged_for_human_review(self) -> bool:
        return len(self.uncertainty_flags) > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "issue": self.issue,
            "category": self.category,
            "no_regression": self.no_regression.as_dict(),
            "n_uncertainty_flags": len(self.uncertainty_flags),
            "flagged_for_human_review": self.flagged_for_human_review,
            "shipped": self.shipped,
            "canary_lane": self.canary_lane,
            "decided_at": self.decided_at,
        }


def evaluate_domains(
    candidate: Callable[[Any], list[float]],
    domains: dict[str, list[tuple[Any, bool]]],
    incumbent: Callable[[Any], list[float]],
) -> NoRegressionResult:
    """No-regression gate: for every expert-reviewed domain, the candidate's
    accuracy must be >= the incumbent's. ``domains`` maps domain → list of
    (features, true_outcome)."""
    evals: list[DomainEval] = []
    for domain, samples in domains.items():
        features = [s[0] for s in samples]
        outcomes = [s[1] for s in samples]
        cand_conf = candidate(features)
        inc_conf = incumbent(features)
        cand_eval: ScorerEval = evaluate_scorer(f"candidate-{domain}", cand_conf, outcomes)
        inc_eval: ScorerEval = evaluate_scorer(f"incumbent-{domain}", inc_conf, outcomes)
        # accuracy proxy: Brier is lower-is-better; accuracy = 1 - brier
        evals.append(
            DomainEval(
                domain=domain,
                incumbent_accuracy=round(1.0 - inc_eval.brier, 4),
                candidate_accuracy=round(1.0 - cand_eval.brier, 4),
            )
        )
    return NoRegressionResult(domains=evals)


def flag_uncertain(
    candidate_scores: dict[str, float],
    judge_variance: dict[str, float],
    threshold: float = 0.01,
) -> list[UncertaintyFlag]:
    """Uncertainty gate: samples whose judge variance exceeds the threshold
    go to human review instead of shipping (B2's aleatoric/epistemic split
    feeds this)."""
    flags: list[UncertaintyFlag] = []
    for sample_id, variance in judge_variance.items():
        if variance >= threshold:
            flags.append(UncertaintyFlag(sample_id=sample_id, variance=variance, threshold=threshold))
    return flags


@dataclass
class PatchLifecycle:
    """CACE-aware lifecycle bookkeeping (Sculley et al. / the article's
    three rules): fuse co-triggering patches, retrain on accumulation,
    unload unused patches."""

    patches_by_category: dict[str, list[str]] = field(default_factory=dict)
    co_trigger_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    last_triggered: dict[str, str] = field(default_factory=dict)

    def register(self, patch_id: str, category: str, co_triggers: list[str] | None = None, triggered_at: str | None = None) -> None:
        self.patches_by_category.setdefault(category, []).append(patch_id)
        self.last_triggered[patch_id] = triggered_at or datetime.now(timezone.utc).isoformat()
        for other in co_triggers or []:
            key = tuple(sorted((patch_id, other)))
            self.co_trigger_counts[key] = self.co_trigger_counts.get(key, 0) + 1

    def needs_retrain(self, category: str) -> bool:
        """Rule 2: patches against one category approaching the empirical
        ceiling → fold into a clean retrain (Pletenev et al.)."""
        return len(self.patches_by_category.get(category, [])) >= MAX_PATCHES_PER_CATEGORY

    def fusion_candidates(self, min_co_triggers: int = 3) -> list[tuple[str, str]]:
        """Rule 1: patches firing on overlapping inputs share relational
        neighborhoods → learnable fusion resolves the subspace interference."""
        return [list(k) for k, v in self.co_trigger_counts.items() if v >= min_co_triggers]

    def unload_unused(self, stale_after_days: float, now: str | None = None) -> list[str]:
        """Rule 3: patches not triggered in the window are unloaded."""
        from datetime import datetime as _dt

        now = now or datetime.now(timezone.utc).isoformat()
        now_dt = _dt.fromisoformat(now)
        stale: list[str] = []
        for patch_id, ts in self.last_triggered.items():
            age_days = (now_dt - _dt.fromisoformat(ts)).total_seconds() / 86400.0
            if age_days > stale_after_days:
                stale.append(patch_id)
        return stale


def decide_micro_patch(
    patch_id: str,
    issue: str,
    category: str,
    domains: dict[str, list[tuple[Any, bool]]],
    candidate: Callable[[Any], list[float]],
    incumbent: Callable[[Any], list[float]],
    judge_variance: dict[str, float],
    *,
    uncertainty_threshold: float = 0.01,
    canary_lane: str = "escalation-band",
) -> MicroPatchVerdict:
    """The two-gate decision: no-regression on expert-reviewed domains AND
    no high-uncertainty outputs shipping unflagged. A passing patch is
    released to the canary lane (01's escalation band)."""
    no_reg = evaluate_domains(candidate, domains, incumbent)
    flags = flag_uncertain({}, judge_variance, uncertainty_threshold)
    shipped = no_reg.passed and not flags
    return MicroPatchVerdict(
        patch_id=patch_id,
        issue=issue,
        category=category,
        no_regression=no_reg,
        uncertainty_flags=flags,
        shipped=shipped,
        canary_lane=canary_lane if shipped else None,
        decided_at=datetime.now(timezone.utc).isoformat(),
    )
