import httpx
import pandas as pd
import pytest
import duckdb

from sim_datasets import (
    HoldoutError,
    available_shocks,
    get_dataset,
    require_calibration_ok,
)
from sim_datasets.catalog import load_catalog
from sim_datasets.fred import FredClient, FredIngest


def test_available_shocks_and_metadata():
    shocks = available_shocks()
    assert shocks == [
        "shock-2020-pandemic",
        "shock-2021-supplychain",
        "shock-2022-inflation",
        "shock-2025-tariff",
    ]
    d = get_dataset("shock-2020-pandemic")
    assert d.holdout is False
    assert d.series == ["UNRATE", "RSAFS_INDEX", "CPIAUCSL_YOY", "INDPRO_INDEX"]


def test_2025_is_holdout():
    assert get_dataset("shock-2025-tariff").holdout is True


def test_realized_anchors_present():
    df = get_dataset("shock-2020-pandemic").realized_path(series=["UNRATE"])
    apr = df[(df["series_id"] == "UNRATE") & (df["date"] == pd.Timestamp("2020-04-01"))]
    assert abs(apr["value"].iloc[0] - 14.7) < 1e-6
    jun22 = get_dataset("shock-2022-inflation").realized_path(series=["CPIAUCSL_YOY"])
    peek = jun22[(jun22["date"] == pd.Timestamp("2022-06-01"))]["value"].iloc[0]
    assert abs(peek - 9.1) < 1e-6


def test_vintages_placeholder_metadata():
    v = get_dataset("shock-2021-supplychain").vintages()
    assert len(v) == 4
    assert all(item["placeholder"] for item in v)
    assert all(item["revision_policy"].startswith("point-in-time") for item in v)


def test_as_of_lookahead_free():
    d = get_dataset("shock-2020-pandemic")
    full = d.load(series=["UNRATE"])
    as_of = d.load(series=["UNRATE"], as_of="2020-03-01")
    assert (as_of["date"] <= pd.Timestamp("2020-03-01")).all()
    assert len(as_of) < len(full)


def test_to_parquet_and_duckdb(tmp_path):
    d = get_dataset("shock-2022-inflation")
    path = d.to_parquet(tmp_path)
    assert path.name == "shock-2022-inflation.parquet"
    con = duckdb.connect()
    d.to_duckdb(con, table="s")
    n = con.execute("select count(*) from s").fetchone()[0]
    assert n > 0


def test_holdout_guard_raises():
    with pytest.raises(HoldoutError):
        require_calibration_ok("shock-2025-tariff")
    with pytest.raises(HoldoutError):
        require_calibration_ok(["shock-2020-pandemic", "shock-2025-tariff"])
    with pytest.raises(HoldoutError):
        require_calibration_ok("tariffs-2025")
    # non-holdout passes silently
    require_calibration_ok("shock-2020-pandemic")
    require_calibration_ok([])


def test_fred_client_vintage_point_in_time():
    all_obs = [
        {"date": "2020-02-01", "value": "3.5"},
        {"date": "2020-03-01", "value": "4.4"},
        {"date": "2020-04-01", "value": "14.7"},
    ]
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["vintage"] = request.url.params.get("vintage")
        vintage = received["vintage"]
        obs = [o for o in all_obs if o["date"] <= vintage]
        return httpx.Response(200, json={"observations": obs})

    client = FredClient(api_key="test", transport=httpx.MockTransport(handler))
    df = client.series_observations("UNRATE", vintage_date="2020-03-15")
    assert received["vintage"] == "2020-03-15"
    # point-in-time: Apr 2020 (14.7) is NOT visible as of 2020-03-15
    assert list(df["date"]) == [pd.Timestamp("2020-02-01"), pd.Timestamp("2020-03-01")]
    assert list(df["value"]) == [3.5, 4.4]


def test_fred_ingest_refuses_holdout():
    client = FredClient(api_key="test", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    ingest = FredIngest(client=client, out_dir="/tmp/definitely-unused")
    with pytest.raises(HoldoutError):
        ingest.ingest_shock("shock-2025-tariff", vintages=["2024-12-31"])


def test_macro_catalog():
    catalog = load_catalog()
    unrate = catalog.get("UNRATE")
    assert unrate.frequency == "monthly"
    assert unrate.source == "FRED"
    tariff_series = catalog.for_shock("shock-2025-tariff")
    assert len(tariff_series) == 4
    assert all(s.is_holdout for s in tariff_series)