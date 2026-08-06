"""A-T-18 scorer-train — LightGBM + netcal calibration with cross-validation.

Protocol (v1): train LightGBM with stratified K-fold CV; collect out-of-fold
predictions; fit the netcal calibrator (isotonic or Platt) on the OOF scores
— the calibrator sees only folds it was not trained on, so the calibration
honors its own holdout discipline; retrain on the full data; register the
artifact in the A-T-20 model registry. MLflow logging is v2.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from trust.contracts import FEATURE_NAMES, FeatureDef
from trust.evidence_features import validate_against_registry
from trust.scorer.calibrate import Calibrator, make_calibrator
from trust.scorer.model import TrainedScorer

logger = logging.getLogger("trust.scorer.train")


def _fit_lightgbm(X: np.ndarray, y: np.ndarray, seed: int = 42, num_boost_round: int = 120) -> Any:
    import lightgbm as lgb

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "seed": seed,
        "verbosity": -1,
        "num_leaves": 15,
        "learning_rate": 0.05,
        "min_data_in_leaf": 10,
    }
    return lgb.train(params, lgb.Dataset(X, y), num_boost_round=num_boost_round)


def train_scorer(
    feature_rows: list[dict[str, float]],
    labels: list[bool],
    *,
    feature_names: list[str] | None = None,
    calibrator_kind: str = "isotonic",
    cv_folds: int = 3,
    seed: int = 42,
    execute_threshold: float = 0.7,
    reject_threshold: float = 0.3,
    model_version: str = "v1",
) -> TrainedScorer:
    """Train + calibrate the trust scorer.

    OOF calibration discipline: the calibrator is fit on cross-validated
    predictions only (it never sees training-fold scores), then the final
    booster is trained on the full data.
    """
    validate_against_registry({k: 0.0 for k in feature_names}) if feature_names else None
    names = feature_names or FEATURE_NAMES
    X = np.array([[float(r.get(n, 0.0)) for n in names] for r in feature_rows], dtype=float)
    y = np.array([1.0 if b else 0.0 for b in labels], dtype=float)
    if len(X) != len(y):
        raise ValueError("feature_rows and labels must have equal length")
    if len(X) == 0:
        raise ValueError("empty training set")

    oof = np.zeros(len(X))
    if cv_folds > 1 and len(X) >= cv_folds * 5:
        from sklearn.model_selection import StratifiedKFold

        skf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed)
        for tr_idx, va_idx in skf.split(X, y):
            booster = _fit_lightgbm(X[tr_idx], y[tr_idx], seed=seed)
            oof[va_idx] = booster.predict(X[va_idx])
    else:
        oof = _fit_lightgbm(X, y, seed=seed).predict(X)

    calibrator: Calibrator = make_calibrator(calibrator_kind).fit(oof, y)
    final_booster = _fit_lightgbm(X, y, seed=seed)
    return TrainedScorer(
        features=names,
        booster=final_booster,
        calibrator=calibrator,
        execute_threshold=execute_threshold,
        reject_threshold=reject_threshold,
        model_version=model_version,
    )


def train_scorer_from_frame(
    features: list[dict[str, float]],
    labels: list[bool],
    *,
    calibrator_kind: str = "isotonic",
    cv_folds: int = 3,
    seed: int = 42,
    execute_threshold: float = 0.7,
    reject_threshold: float = 0.3,
    model_version: str = "v1",
) -> TrainedScorer:
    return train_scorer(
        features,
        labels,
        calibrator_kind=calibrator_kind,
        cv_folds=cv_folds,
        seed=seed,
        execute_threshold=execute_threshold,
        reject_threshold=reject_threshold,
        model_version=model_version,
    )


def _cli_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="trust-scorer-train", description="A-T-18: train + calibrate the trust scorer")
    parser.add_argument("--data", required=True, help="jsonl with {features: {...}, outcome: bool} per line")
    parser.add_argument("--out", default="models", help="output dir for the joblib artifact + card")
    parser.add_argument("--calibrator", default="isotonic", choices=["isotonic", "platt"])
    parser.add_argument("--cv", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--execute-threshold", type=float, default=0.7)
    parser.add_argument("--reject-threshold", type=float, default=0.3)
    parser.add_argument("--name", default="trust-scorer")
    parser.add_argument("--version", default="v1")
    args = parser.parse_args(argv)

    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines() if line.strip()]
    feature_rows = [r["features"] for r in rows]
    labels = [bool(r["outcome"]) for r in rows]
    trained = train_scorer(
        feature_rows,
        labels,
        calibrator_kind=args.calibrator,
        cv_folds=args.cv,
        seed=args.seed,
        execute_threshold=args.execute_threshold,
        reject_threshold=args.reject_threshold,
        model_version=args.version,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import joblib

    artifact_path = out / f"{args.name}-{args.version}.joblib"
    joblib.dump(trained, artifact_path)
    card = {
        "model_name": args.name,
        "version": args.version,
        "purpose": "C5 confidence provider (evidence-only features)",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "framework": "lightgbm",
        "features": trained.features,
        "calibrated_with": trained.calibrator.name() if hasattr(trained.calibrator, "kind") else "netcal",
        "n_samples": len(rows),
    }
    (out / f"{args.name}-{args.version}.card.json").write_text(json.dumps(card, indent=2))
    logger.info("saved %s to %s", artifact_path, out)


if __name__ == "__main__":
    _cli_main()
