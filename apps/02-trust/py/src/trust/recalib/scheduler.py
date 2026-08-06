"""A-T-32 recalibration-scheduler — APScheduler → scorer-train, plus the
band-drift report.

The schedulable unit is a plain function (``trigger_retrain``) so tests never
need a running scheduler; the APScheduler wrapper around it is the compose
service (:8041). The band-drift report tracks per-band accuracy over the
confirmed decision log — the escalation band tightening 01 sees.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from trust.contracts import DecisionRecord, band_for
from trust.recalib.decision_log import OutcomeStore


@dataclass
class BandDriftReport:
    per_band: dict[str, dict[str, float]] = field(default_factory=dict)
    previous_band_accuracy: dict[str, float] = field(default_factory=dict)
    n_labeled: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_labeled": self.n_labeled,
            "per_band": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in self.per_band.items()},
            "previous_band_accuracy": self.previous_band_accuracy,
        }


def band_drift_report(
    records: list[DecisionRecord],
    execute_threshold: float = 0.7,
    reject_threshold: float = 0.3,
    previous: dict[str, float] | None = None,
    score_key: str = "score",
) -> BandDriftReport:
    """Per-band outcome accuracy over the confirmed log, vs the previous run.

    The band assignment needs the gate score; 01's log stores it inside
    ``confidenceFeatures[score_key]`` (the C5 drop-in writes it back as
    ``score``). Rows without it fall to the middle band.
    """
    labeled = [r for r in records if r.outcome is not None]
    bands: dict[str, list[float]] = {"execute-band": [], "escalation-band": [], "reject-band": []}
    for r in labeled:
        confidence = float(r.confidenceFeatures.get(score_key, 0.5)) if score_key in r.confidenceFeatures else 0.5
        band = band_for(confidence, execute_threshold, reject_threshold)
        bands[band].append(1.0 if r.outcome else 0.0)
    per_band: dict[str, dict[str, float]] = {}
    for band, outcomes in bands.items():
        n = len(outcomes)
        per_band[band] = {"n": n, "accuracy": float(sum(outcomes) / n) if n else 0.0}
    return BandDriftReport(
        per_band=per_band,
        previous_band_accuracy=previous or {},
        n_labeled=len(labeled),
    )


@dataclass
class RetrainReport:
    n_labels: int
    old_version: str
    new_version: str
    trained_at: str
    drift: BandDriftReport
    saved_artifact: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_labels": self.n_labels,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "trained_at": self.trained_at,
            "drift": self.drift.as_dict(),
            "saved_artifact": self.saved_artifact,
        }


def trigger_retrain(
    store: OutcomeStore,
    train_fn: Callable[[list[dict[str, float]], list[bool]], Any],
    *,
    current_version: str = "v0",
    execute_threshold: float = 0.7,
    reject_threshold: float = 0.3,
    out_dir: str = "models",
    name: str = "trust-scorer",
) -> RetrainReport:
    """The scheduler's payload: consume the confirmed log, retrain the scorer,
    save it, and report band drift. Pure and testable — APScheduler never
    runs in tests."""
    labeled = store.labeled()
    features, labels = store.training_frame()
    if len(labels) < 20:
        raise ValueError(f"not enough confirmed outcomes to retrain: {len(labels)} < 20")
    drift = band_drift_report(labeled, execute_threshold, reject_threshold)
    new_version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    trained = train_fn(features, labels)
    import joblib
    from pathlib import Path

    artifact = Path(out_dir) / f"{name}-{new_version}.joblib"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(trained, artifact)
    return RetrainReport(
        n_labels=len(labels),
        old_version=current_version,
        new_version=new_version,
        trained_at=datetime.now(timezone.utc).isoformat(),
        drift=drift,
        saved_artifact=str(artifact),
    )


class RecalibrationScheduler:
    """APScheduler wrapper (:8041). ``trigger`` is the scheduled callable;
    ``start``/``stop`` manage the background scheduler. Tests exercise
    ``trigger_retrain`` directly."""

    def __init__(self, trigger: Callable[[], RetrainReport], interval_minutes: int = 60) -> None:
        self._trigger = trigger
        self._interval_minutes = interval_minutes
        self._scheduler = None

    def start(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(self._trigger, "interval", minutes=self._interval_minutes, id="scorer-retrain")
        self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None


def _cli_main() -> None:
    """Standalone recalibration run (no scheduler): consume the local log,
    retrain if enough outcomes exist, write the drift report."""
    import argparse
    import json
    from pathlib import Path

    from trust.recalib.decision_log import DecisionLogConsumer, InMemoryDecisionLogSource

    parser = argparse.ArgumentParser(prog="trust-calibrate", description="A-T-32: retrain on the confirmed log + band drift report")
    parser.add_argument("--out", default="models", help="output dir for the model artifact and drift report")
    args = parser.parse_args()

    source = InMemoryDecisionLogSource()
    consumer = DecisionLogConsumer(source)
    consumed = consumer.poll_once()
    from trust.scorer.train import train_scorer

    try:
        report = trigger_retrain(
            consumer.store,
            lambda f, y: train_scorer(f, y, model_version="calibrate"),
            out_dir=args.out,
        )
    except ValueError as err:
        print(json.dumps({"status": "skipped", "consumed": consumed, "reason": str(err)}))
        return
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "band_drift.json").write_text(json.dumps(report.as_dict(), indent=2))
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    _cli_main()
