import numpy as np

from sim_engine import (
    Agent,
    AgentProto,
    CascadeBehaviourAdapter,
    Decision,
    EventBus,
    EnsembleRunResult,
    EnsembleStore,
    SimulationClock,
    World,
    get_adapter,
    list_adapters,
    register_adapter,
    remove_adapter,
    run_trajectory,
)


def _positive_rule(world, rng):
    return Decision(agent_id="x", action="adjust", magnitude=1.0)


def _jitter_rule(world, rng):
    return Decision(agent_id="x", action="adjust", magnitude=float(rng.normal(0, 1)))


def _make_agents(rule):
    return [Agent(AgentProto(id=f"a{i}", rule=rule), role="firm") for i in range(2)]


def test_swarm_deterministic_in_seed():
    w1, w2 = World("w"), World("w")
    agents = _make_agents(_positive_rule)
    t1 = run_trajectory(w1, agents, steps=3, seed=7)
    t2 = run_trajectory(w2, agents, steps=3, seed=7)
    assert np.allclose(t1.values, t2.values)
    assert t1.values.shape == (3,)


def test_swarm_different_seed_differs():
    w1, w2 = World("w"), World("w")
    t1 = run_trajectory(w1, _make_agents(_jitter_rule), steps=5, seed=1)
    t2 = run_trajectory(w2, _make_agents(_jitter_rule), steps=5, seed=2)
    assert not np.allclose(t1.values, t2.values)


def test_cascade_adapter_deterministic_and_registered():
    assert "cascade-behaviour" in list_adapters()
    adapter = get_adapter("cascade-behaviour")
    seed = {"history": [100.0] * 12, "world": {"cascade": 0.0, "vol": 0.02, "noise": 0.01}, "seed": 9}
    f1 = adapter.simulate(seed, horizon=3, rng=np.random.default_rng(0), n_members=8)
    f2 = adapter.simulate(dict(seed), horizon=3, rng=np.random.default_rng(0), n_members=8)
    assert np.allclose(f1.values, f2.values)
    assert f1.values.shape == (8, 3)
    lo, hi = f1.interval(0.8)
    assert lo.shape == (3,) and hi.shape == (3,)


def test_cascade_adapter_cascade_widens_spread():
    calm = CascadeBehaviourAdapter().simulate(
        {"history": [100.0] * 12, "world": {"cascade": 0.0, "vol": 0.02, "noise": 0.01}, "seed": 3},
        horizon=6, rng=np.random.default_rng(1), n_members=60,
    )
    storm = CascadeBehaviourAdapter().simulate(
        {"history": [100.0] * 12, "world": {"cascade": 0.5, "shift_magnitude": 0.15, "vol": 0.02, "noise": 0.01}, "seed": 3},
        horizon=6, rng=np.random.default_rng(1), n_members=60,
    )
    assert storm.quantile(0.9).max() > calm.quantile(0.9).max()


def test_ensemble_store_roundtrip(tmp_path):
    store = EnsembleStore(path=str(tmp_path / "s.duckdb"))
    vals = np.arange(20.0).reshape(4, 5)
    store.save(EnsembleRunResult(run_id="r1", shock_id="s", simulator="cascade-behaviour", seed=7, horizon=5, values=vals))
    loaded = store.load("r1")
    assert np.allclose(loaded.values, vals)
    assert store.to_parquet("r1", tmp_path / "r1.parquet").exists()
    store.close()


def test_events_and_clock():
    bus = EventBus()
    seen = []
    bus.subscribe(lambda ev: seen.append(ev.kind))
    bus.publish("airdrop", {})
    assert seen == ["airdrop"]
    assert SimulationClock().tick() == 1


def test_adapter_registry_remove_restore():
    remove_adapter("cascade-behaviour")
    assert "cascade-behaviour" not in list_adapters()
    register_adapter(CascadeBehaviourAdapter())
    assert "cascade-behaviour" in list_adapters()