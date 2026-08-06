import numpy as np
import pytest

from sim_datasets import HoldoutError, get_dataset
from sim_baseline.adapters import ArimaAdapter, LightGBMAdapter
from sim_baseline.arima import AutoArimaForecaster
from sim_baseline.hub import backtest_lookahead_free
from sim_baseline.lightgbm import LightGBMQuantileForecaster, split_conformal_interval


def _rng():
    return np.random.default_rng(42)


def test_split_conformal_quantile_guarantee():
    # calibration residuals drawn from |N(0,1)|; alpha=0.2 width ~= z(0.9)
    rng = _rng()
    resid = np.abs(rng.normal(0, 1, 5000))
    w = split_conformal_interval(resid, alpha=0.2)
    assert 1.0 < w < 1.5  # z(0.9)≈1.28


def test_arima_forecast_shapes():
    rng = _rng()
    y = np.cumsum(rng.normal(0, 1, 48)) + 100
    model = AutoArimaForecaster(horizon=6)
    model.fit(y)
    fc = model.predict()
    assert fc["mean"].shape == (6,)
    assert fc["lo-50"].shape == (6,)
    ens = model.as_ensemble(rng, n_members=50)
    assert ens.shape == (50, 6)
    assert np.all(np.isfinite(ens))


def test_lightgbm_quantile_ordering():
    rng = _rng()
    y = np.sin(np.linspace(0, 4 * np.pi, 60)) * 5 + 100 + rng.normal(0, 0.5, 60)
    model = LightGBMQuantileForecaster(horizon=6, conformal=True)
    model.fit(y)
    fc = model.predict(float(y[-1]), rng)
    for h in range(6):
        assert fc["q05"][h] <= fc["q20"][h] <= fc["q50"][h] <= fc["q80"][h] <= fc["q95"][h]
    ens = model.as_ensemble(float(y[-1]), rng, n_members=100)
    assert ens.shape == (100, 6)


def test_backtest_lookahead_free_uses_only_asof_history():
    dataset = get_dataset("shock-2020-pandemic")
    rng = _rng()
    records = backtest_lookahead_free(
        dataset,
        series_id="UNRATE",
        adapter_factory=lambda: ArimaAdapter(horizon=3),
        scoring_as_of=["2020-02-01", "2020-05-01"],
        horizon=3,
        rng=rng,
    )
    assert len(records) == 2
    # fold 1 trained on data <= 2020-02-01: Apr 2020 spike (14.7) NOT in train
    first = records[0]
    assert len(first.realized) == 3
    assert first.realized.max() >= 14.0  # realized window catches the spike
    assert first.forecast.method == "auto-arima"
    assert first.forecast.ensemble.shape[0] == 200


def test_backtest_refuses_holdout():
    dataset = get_dataset("shock-2025-tariff")
    with pytest.raises(HoldoutError):
        backtest_lookahead_free(
            dataset,
            series_id="IMPGSA",
            adapter_factory=lambda: ArimaAdapter(horizon=3),
            scoring_as_of=["2025-04-01"],
            horizon=3,
            rng=_rng(),
        )


def test_lightgbm_adapter_in_hub():
    dataset = get_dataset("shock-2022-inflation")
    records = backtest_lookahead_free(
        dataset,
        series_id="CPIAUCSL_YOY",
        adapter_factory=lambda: LightGBMAdapter(horizon=3, ensemble_members=50),
        scoring_as_of=["2022-03-01"],
        horizon=3,
        rng=_rng(),
    )
    assert records[0].forecast.ensemble.shape == (50, 3)