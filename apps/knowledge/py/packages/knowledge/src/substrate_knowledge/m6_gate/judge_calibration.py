"""Judge calibration loop (A-K-25 calibration surface, Airbnb EDD §2.2.1).

A virtual judge is not trustworthy until calibrated: golden set WITH bad
examples → judge vs human labels → agreement (Cohen's kappa / Krippendorff's
alpha) → disagreement analysis → rubric/few-shot refinement → re-run until
the target (high-80s–90s) is hit. Recalibrate periodically as failure modes
evolve (02's APScheduler hooks `run_calibration`).

The loop is judge-agnostic: any ``VerdictClassifier`` can be calibrated, so
the deterministic stub, the Ollama judge and the Outlines judge share one
discipline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from substrate_knowledge.core.metrics import cohens_kappa, krippendorff_alpha
from substrate_knowledge.m6_gate.verdict_classifier import DeterministicVerdictClassifier, VerdictClassifier

DEFAULT_AGREEMENT_TARGET = 0.85  # Airbnb: high-80s–90s


@dataclass(frozen=True)
class GoldenCase:
    claim: str
    evidence: list[str]
    human_label: str  # support | contradict | silent


@dataclass
class Disagreement:
    claim: str
    evidence: list[str]
    human: str
    judge: str
    prob: float


@dataclass
class CalibrationReport:
    n_cases: int
    kappa: float
    alpha: float
    n_disagreements: int
    disagreements: list[Disagreement] = field(default_factory=list)
    error_breakdown: dict[str, int] = field(default_factory=dict)
    target: float = DEFAULT_AGREEMENT_TARGET
    passed: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "n_cases": self.n_cases,
            "kappa": round(self.kappa, 4),
            "alpha": round(self.alpha, 4),
            "n_disagreements": self.n_disagreements,
            "error_breakdown": self.error_breakdown,
            "target": self.target,
            "passed": self.passed,
            "sample_disagreements": [
                {"claim": d.claim, "human": d.human, "judge": d.judge, "prob": d.prob}
                for d in self.disagreements[:10]
            ],
        }


def _error_type(human: str, judge: str) -> str:
    if human == "silent" and judge != "silent":
        return "false-positive-verdict"  # judged support/contradict on silence
    if human != "silent" and judge == "silent":
        return "missed-verdict"  # silence when evidence says something
    if human != judge:
        return "wrong-direction"  # support vs contradict flip
    return "agreed"


def run_calibration(
    golden: list[GoldenCase],
    classifier: VerdictClassifier | None = None,
    target: float = DEFAULT_AGREEMENT_TARGET,
) -> CalibrationReport:
    """Run the judge against a golden set (WITH bad examples) and measure
    agreement vs human labels, with disagreement analysis + error breakdown
    that drives rubric refinement. Returns the report; ``passed`` is true
    when agreement meets the target."""
    classifier = classifier or DeterministicVerdictClassifier()
    judge_labels: list[str] = []
    human_labels: list[str] = []
    disagreements: list[Disagreement] = []

    for case in golden:
        verdict = classifier.classify(case.claim, case.evidence)
        judge_labels.append(verdict.kind.value)
        human_labels.append(case.human_label)
        if verdict.kind.value != case.human_label:
            disagreements.append(
                Disagreement(case.claim, case.evidence, case.human_label, verdict.kind.value, verdict.prob)
            )

    kappa = cohens_kappa(judge_labels, human_labels)
    alpha = krippendorff_alpha([[j, h] for j, h in zip(judge_labels, human_labels)])

    breakdown: dict[str, int] = {}
    for d in disagreements:
        t = _error_type(d.human, d.judge)
        breakdown[t] = breakdown.get(t, 0) + 1

    return CalibrationReport(
        n_cases=len(golden),
        kappa=kappa,
        alpha=alpha,
        n_disagreements=len(disagreements),
        disagreements=disagreements,
        error_breakdown=breakdown,
        target=target,
        passed=kappa >= target,
    )


def refine_rubric_suggestions(report: CalibrationReport) -> list[str]:
    """Rubric refinement hints driven by the disagreement analysis — the
    article's "analyze disagreements, refine the prompt, re-run the loop"."""
    hints: list[str] = []
    fp = report.error_breakdown.get("false-positive-verdict", 0)
    missed = report.error_breakdown.get("missed-verdict", 0)
    wrong = report.error_breakdown.get("wrong-direction", 0)
    if fp:
        hints.append(
            f"false-positive-verdict x{fp}: judge over-verdicts on silence — add a "
            "'no shared topic or no stance signal → silent' rule/few-shot example"
        )
    if missed:
        hints.append(
            f"missed-verdict x{missed}: judge stays silent on real evidence — add "
            "'shared entity + stance word → verdict' rule/few-shot example"
        )
    if wrong:
        hints.append(
            f"wrong-direction x{wrong}: support/contradict flips — check polarity "
            "lexicon and role directionality (reversed roles need the real judge)"
        )
    if not hints:
        hints.append("no rubric refinement suggested — agreement target met")
    return hints


def calibrate_until_target(
    golden: list[GoldenCase],
    refine: Callable[[CalibrationReport], list[GoldenCase]],
    max_rounds: int = 5,
    target: float = DEFAULT_AGREEMENT_TARGET,
) -> tuple[CalibrationReport, int]:
    """The full loop: measure → refine (rubric/few-shot → new golden
    encoding) → re-run, until the target is hit or rounds are exhausted.
    Returns (final report, rounds used)."""
    current = golden
    for round_no in range(1, max_rounds + 1):
        report = run_calibration(current, target=target)
        if report.passed or round_no == max_rounds:
            return report, round_no
        current = refine(report)
    return run_calibration(current, target=target), max_rounds
