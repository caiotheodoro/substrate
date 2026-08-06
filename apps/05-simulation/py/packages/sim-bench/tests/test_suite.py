"""A-S-05 — simbench-suite: golden numbers with fixed seeds."""

import numpy as np
import pytest

from sim_bench import (
    AdapterRegistry,
    BenchMatrixRunner,
    brier_score,
    coverage,
    crps_ensemble,
    score_ensemble,
    tail_loss,
)
from sim_engine.adapter_sdk import EnsembleForecast


def _golden_forecast(seed: int = 0, horizon: int = 200, n: int = 500):
    rng = np.random.default_rng(seed)
    values = rng.normal(100, 5, size=(n, horizon)) + np.linspace(0, 2, horizon)
    return EnsembleForecast(values=values, horizon=horizon)


def _golden_realized(seed: int = 0, horizon: int = 200):
    # a held-out ensemble member: by construction it lives inside the
    # ensemble's own distribution, so coverage is calibratable
    rng = np.random.default_rng(seed)
    values = rng.normal(100, 5, size=(500, horizon)) + np.linspace(0, 2, horizon)
    return values[13]


def test_golden_coverage_is_calibrated():
    fc = _golden_forecast()
    y = _golden_realized()
    assert coverage(fc, y, 0.50) == pytest.approx(0.50, abs=0.05)
    assert coverage(fc, y, 0.80) == pytest.approx(0.80, abs=0.05)
    assert coverage(fc, y, 0.95) == pytest.approx(0.95, abs=0.05)


def test_golden_crps_matches_scipy_distribution():
    fc = _golden_forecast(horizon=24)
    y = _golden_realized(horizon=24)
    crps = crps_ensemble(fc.values, y)
    assert 0.0 < crps < 10.0
    result = score_ensemble(fc, y)
    assert result.scores["crps"] == pytest.approx(crps)


def test_tail_loss_is_zero_when_realized_stays_in_body():
    fc = _golden_forecast(horizon=24)
    y = _golden_realized(horizon=24) + 3.0  # shift upward → no downside tail
    assert tail_loss(fc, y, alpha=0.05) == 0.0


def test_tail_loss_positive_on_downside_break():
    fc = _golden_forecast(horizon=24)
    y = _golden_realized(horizon=24) - 25.0
    assert tail_loss(fc, y, alpha=0.05) > 5.0


def test_brier_score_between_zero_and_one():
    fc = _golden_forecast(horizon=24)
    y = _golden_realized(horizon=24)
    assert 0.0 < brier_score(fc, y) < 0.5


def test_horizon_mismatch_raises():
    fc = EnsembleForecast(values=np.zeros((5, 3)), horizon=3)
    with pytest.raises(ValueError):
        score_ensemble(fc, np.zeros(4))


def test_score_meta_survives():
    fc = _golden_forecast()
    result = score_ensemble(fc, _golden_realized(), meta={"shock_id": "x"})
    assert result.meta["shock_id"] == "x"


class _FakeAdapter:
    method = "fake-golden"

    def simulate(self, world_seed, horizon, rng, n_members):
        rng = np.random.default_rng(seed_from(world_seed))
        return _golden_forecast(horizon=horizon, n=n_members)


def seed_from(world_seed: dict) -> int:
    return abs(hash(str(world_seed))) % (2**31)


def test_registry_sqlite_roundtrip(tmp_path):
    reg = AdapterRegistry(tmp_path / "registry.db")
    reg.register("fake-golden", "tests.test_suite")
    assert "fake-golden" in reg.list()
    reg.close()


def test_matrix_runner_writes_parquet(tmp_path):
    class FakeDataset:
        id = "shock-2020-pandemic"
        scenario_id = "covid-2020"

        def realized_path(self):
            import pandas as pd

            return pd.DataFrame(
                {
                    "date": pd.date_range("2020-03-01", periods=24, freq="MS"),
                    "series_id": ["UNRATE"] * 24,
                    "value": np.linspace(4.0, 12.0, 24),
                }
            )

    class Adapter:
        method = "fake-golden"

        def simulate(self, world_seed, horizon, rng, n_members):
            return _golden_forecast(seed=0, horizon=horizon, n=n_members)

    runner = BenchMatrixRunner(
        adapters={"fake-golden": Adapter()},
        datasets={"shock-2020-pandemic": FakeDataset()},
    )
    frame = runner.run(shock_ids=["shock-2020-pandemic"], seeds=[0, 1], n_members=50)
    assert len(frame) == 2
    assert {"coverage_50", "brier", "crps", "tail_loss"} <= set(frame.columns)
    assert frame["vintaged"].all()
    out = runner.save(frame, tmp_path / "matrix.parquet")
    assert out.exists()


def test_matrix_runner_refuses_holdout():
    runner = BenchMatrixRunner(adapters={}, datasets={})
    with pytest.raises(Exception):
        runner.run(shock_ids=["shock-2025-tariff"], seeds=[0])