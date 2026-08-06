from fastapi.testclient import TestClient

from sim_cross import SimDB, create_app
from sim_cross.api import make_spec


def test_health():
    client = TestClient(create_app(SimDB()))
    assert client.get("/health").json() == {"ok": True}


def test_scenarios_lists_four_with_holdout_flag():
    client = TestClient(create_app(SimDB()))
    docs = client.get("/scenarios").json()
    ids = {d["id"] for d in docs}
    assert ids == {"covid-2020", "supplychain-2021", "inflation-2022", "tariffs-2025"}
    holdouts = {d["id"] for d in docs if d["holdout"]}
    assert holdouts == {"tariffs-2025"}


def test_scenario_detail_and_404():
    client = TestClient(create_app(SimDB()))
    doc = client.get("/scenarios/covid-2020").json()
    assert doc["window"] == "2020-03/2020-06"
    assert client.get("/scenarios/nope").status_code == 404


def test_replay_persists_run_and_events():
    db = SimDB()
    client = TestClient(create_app(db))
    res = client.post("/injections/covid-2020/replay", params={"steps": 6})
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == "replay-covid-2020"
    assert len(body["frames"]) == 6
    assert body["events"]
    assert db.runs_df()["shock_id"].tolist() == ["covid-2020"]
    assert len(db.events_df("replay-covid-2020")) >= 1


def test_replay_holdout_is_scoring_only():
    client = TestClient(create_app(SimDB()))
    res = client.post("/injections/tariffs-2025/replay", params={"steps": 2})
    # scoring path allowed (allow_scoring=True) but flagged as holdout
    assert res.status_code == 200
    assert res.json()["holdout"] is True


def test_simdb_scores_roundtrip():
    import pandas as pd

    db = SimDB()
    frame = pd.DataFrame(
        {
            "shock_id": ["shock-2020-pandemic"],
            "method": ["arima"],
            "seed": [0],
            "as_of": ["2020-03-01"],
            "coverage_50": [0.5],
            "brier": [0.2],
        }
    )
    assert db.add_scores(frame) == 1
    assert len(db.scores_df()) == 1