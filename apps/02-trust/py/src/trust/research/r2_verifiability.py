"""A-T-35 r2-verifiability-audit — what fraction of the workload is
unverifiable, and what does that cost?

An action is *unverifiable* when none of the four evidence channels exist
(no tool ran, retrieval is silent, no schema, no outcome history). For those
the gate has no evidence and must default-escalate (or reject). This analysis
quantifies the fraction where that is the binding constraint, across a
workload mix, and emits the numbers + a PNG to ``docs/validation/``.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from trust.confbench.tasks import ConfBenchTask
from trust.evidence_features import EvidenceFeatures
from trust.gated_data.models import SeedRecord
from trust.gated_data.verifiability import VerifiabilityVerdict, assess_verifiability


def audit_tasks(tasks: list[ConfBenchTask]) -> dict[str, Any]:
    """Audit a ConfBench-style task workload for checkability."""
    verdicts = [VerifiabilityVerdict(t.checkable, False, {}) for t in tasks]
    return _summarize([v.checkable for v in verdicts], [len(t.evidence.features) for t in tasks], kinds=_kind_counts(tasks))


def audit_seeds(seeds: list[SeedRecord]) -> dict[str, Any]:
    verdicts = [assess_verifiability(s) for s in seeds]
    return _summarize(
        [v.checkable for v in verdicts],
        [len(v.signals) for v in verdicts],
        kinds=Counter(s.signal_kinds[0] if s.signal_kinds else "none" for s in seeds),
    )


def _kind_counts(tasks: list[ConfBenchTask]) -> Counter[str]:
    return Counter(t.kind for t in tasks)


def _summarize(checkable_flags: list[bool], n_signals: list[int], kinds: Counter[str]) -> dict[str, Any]:
    n = len(checkable_flags)
    if n == 0:
        return {"n": 0, "fraction_unverifiable": 0.0, "default_escalate_fraction": 0.0}
    unverifiable = sum(1 for c in checkable_flags if not c)
    fraction_unverifiable = unverifiable / n
    return {
        "n": n,
        "n_unverifiable": unverifiable,
        "fraction_unverifiable": round(fraction_unverifiable, 4),
        "default_escalate_fraction": round(fraction_unverifiable, 4),
        "signal_kind_mix": dict(kinds.most_common()),
        "mean_signals_per_verified_sample": round(sum(n_signals) / n, 3),
    }


def run_r2(tasks: list[ConfBenchTask] | list[SeedRecord] | None = None, out_dir: str | Path | None = None) -> dict[str, Any]:
    """Default workload = the ConfBench base split mixed with a batch of
    unverifiable records (the realistic case: some actions simply have no
    evidence channel)."""
    if tasks is None:
        from trust.confbench.tasks import generate_tasks

        base = generate_tasks(200, seed=404)
        unverifiable = [ConfBenchTask(
            task_id=f"unver-{i}",
            kind="outcome",
            difficulty=0.5,
            latent_v=0.0,
            evidence=EvidenceFeatures({}),
            self_report={"logprob_norm": 0.7, "self_consistency": 0.6, "verbalized": 0.8},
            outcome=False,
        ) for i in range(80)]
        workload = base + unverifiable
    else:
        workload = list(tasks)

    if workload and isinstance(workload[0], ConfBenchTask):
        result = audit_tasks(workload)  # type: ignore[arg-type]
    else:
        result = audit_seeds(workload)  # type: ignore[arg-type]
    result["recommendation"] = (
        "unverifiable workload must default-escalate; if the fraction is material, "
        "the binding constraint is outcome collection, not calibration"
    )
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "r2_verifiability.json").write_text(json.dumps(result, indent=2))
        _write_png(result, str(out / "r2_verifiability.png"))
    return result


def _write_png(result: dict[str, Any], path: str) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    mix = result["signal_kind_mix"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 4))
    ax1.bar(["verifiable", "unverifiable"], [1 - result["fraction_unverifiable"], result["fraction_unverifiable"]], color=["#2a9d8f", "#e76f51"])
    ax1.set_title("r2 — verifiability of workload")
    ax1.set_ylabel("fraction")
    ax2.bar(mix.keys(), mix.values())
    ax2.set_title("signal kind mix")
    ax2.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return True


def _cli_main() -> None:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="trust-r2", description="A-T-35: verifiability audit")
    parser.add_argument("--out", default="docs/validation", help="output dir for JSON + PNG artifacts")
    args = parser.parse_args()
    result = run_r2(out_dir=args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli_main()
