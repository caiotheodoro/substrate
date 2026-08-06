import numpy as np
import pytest
from jsonschema import ValidationError

from sim_engine import Sector, World
from sim_datasets import HoldoutError
from sim_injection import (
    InjectionRuntime,
    InjectionSpec,
    build_shock_seed,
    get_scenario,
    list_scenarios,
    validate_shock_spec,
)


def _make():
    w = World("test")
    w.add_sector(Sector("goods", demand=1.0, supply=1.0, price=1.0, shock_exposure=0.5))
    w.add_sector(Sector("labor", demand=1.0, supply=1.0, price=1.0, shock_exposure=0.3))
    w.add_sector(Sector("finance", demand=1.0, supply=1.0, price=1.0, shock_exposure=0.7))
    return w


def test_spec_validation():
    good = {
        "id": "in-x", "profile": "trade-policy shock", "magnitude": 1.0,
        "channels": ["tariff-rate"], "start": "2025-04",
    }
    assert validate_shock_spec(good)["id"] == "in-x"
    bad = {"id": "x", "profile": "nonsense", "magnitude": "high"}
    with pytest.raises(ValidationError):
        validate_shock_spec(bad)


def test_list_and_get_scenarios():
    ids = list_scenarios()
    assert ids == ["covid-2020", "supplychain-2021", "inflation-2022", "tariffs-2025"]
    assert get_scenario("tariffs-2025").is_holdout
    assert get_scenario("covid-2020").window == "2020-03/2020-06"


def test_injection_runtime_replay_changes_world():
    world = _make()
    spec = InjectionSpec.from_dict(
        {
            "id": "in-test", "profile": "trade-policy shock", "magnitude": 1.0,
            "channels": ["policy-rate"], "start": "2022-03", "ramp": "step", "horizon": 4,
        }
    )
    runtime = InjectionRuntime(world, spec)
    frames = list(runtime.replay(3))
    assert len(frames) == 3
    assert frames[0].multiplier > 0
    assert world.sectors["finance"].price > 1.0
    assert any(e.kind == "injection" for e in world.events.history)


def test_build_shock_seed_uses_only_preshook_history():
    seed = build_shock_seed("covid-2020", as_of="2020-02-01")
    assert seed["as_of"] == "2020-02-01"
    assert max(seed["history"]) < 5.0  # 14.7% (Apr 2020) must NOT appear pre-shock
    assert len(seed["history"]) >= 12
    assert seed["world"]["cascade"] == 0.0


def test_build_shock_seed_tariff_holdout_refuses():
    with pytest.raises(HoldoutError):
        build_shock_seed("tariffs-2025", allow_scoring=False)
    seed = build_shock_seed("tariffs-2025", as_of="2025-01-01", allow_scoring=True)
    assert seed["as_of"] == "2025-01-01"


def test_ramp_multiplier():
    spec = InjectionSpec.from_dict(
        {
            "id": "r", "profile": "trade-policy shock", "magnitude": 1.0,
            "channels": ["import-cost"], "start": "2025-04", "ramp": "linear", "horizon": 10,
        }
    )
    runtime = InjectionRuntime(_make(), spec)
    assert runtime.multiplier_at(0) == 0.0
    assert runtime.multiplier_at(5) == pytest.approx(0.5)
    assert runtime.multiplier_at(20) == 1.0