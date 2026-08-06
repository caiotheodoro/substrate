import numpy as np
import pytest

from sim_shared.cost import CostMeter
from sim_presence import (
    AgentPresence,
    CircumplexState,
    PADState,
    PresencePolicy,
    PresenceRoom,
    SocialLog,
    act_lite_step,
)
from sim_presence import InMemoryMemoryStore
from sim_presence.affect_models import event_appraisal, pad_to_circumplex


def _agents(agents, rounds=20, seed=0, checkin_probability=0.12):
    log = SocialLog()
    room = PresenceRoom(
        agents=agents, social_log=log, run_id="room-t", seed=seed,
        rounds=rounds, checkin_probability=checkin_probability,
    )
    return room, log


def test_urgency_balance():
    a = AgentPresence(id="one", pressure=1.0, inhibition=0.1, motivation=0.5)
    b = AgentPresence(id="two", pressure=1.5, inhibition=2.0, motivation=0.2)
    assert a.urgency() > 0
    assert b.wants_silence
    assert b.urgency() < 0
    assert a.urgency() > b.urgency()


def test_inhibited_agent_emits_silence_not_a_turn():
    a = AgentPresence(id="A", pressure=0.0, inhibition=0.1, motivation=0.6)
    b = AgentPresence(id="B", pressure=2.0, inhibition=3.0, motivation=0.1)
    room, log = _agents([a, b], rounds=12, checkin_probability=0.5)
    room.run()
    kinds = [e.kind for e in log.events()]
    assert "silence" in kinds
    silence = [e for e in log.events() if e.kind == "silence"]
    assert all(e.payload["agent"] == "B" for e in silence)
    b_turns = [e for e in log.events() if e.payload.get("agent") == "B" and e.kind != "silence"]
    assert b_turns == []


def test_moves_driven_by_urgency_not_round_robin():
    hi = AgentPresence(id="X", motivation=0.9, pressure=0.0, inhibition=0.0)
    mid = AgentPresence(id="Y", motivation=0.5, pressure=0.0, inhibition=0.0)
    low = AgentPresence(id="Z", motivation=0.2, pressure=0.0, inhibition=0.0)
    room, log = _agents([hi, mid, low], rounds=30, seed=3)
    room.run()

    counts = {"X": 0, "Y": 0, "Z": 0}
    for ev in log.events():
        if ev.kind in ("post", "reply"):
            counts[ev.payload["agent"]] += 1
    assert counts["X"] > counts["Z"]
    assert counts["X"] >= counts["Y"]
    # all three are present but the ordering is drive-weighted, not an even cycle
    assert counts["X"] + counts["Y"] + counts["Z"] == len(
        [e for e in log.events() if e.kind in ("post", "reply")]
    )


def test_social_log_chain_integrity_and_c1_shape():
    log = SocialLog()
    log.write(run_id="r1", kind="post", payload={"agent": "A", "content": "hi"})
    log.write(run_id="r1", kind="reply", payload={"agent": "B", "content": "yo", "target": "A"})
    log.write(run_id="r1", kind="silence", payload={"agent": "C", "cause": "inhibition"})
    assert log.chain_integrity()
    assert [e.seq for e in log.events()] == [1, 2, 3]
    c1 = log.to_c1()
    assert all(e["family"] == "stream" for e in c1)
    assert c1[2]["idempotencyKey"] == "r1:silence:3"


def test_social_log_persists_and_reloads(tmp_path):
    p = tmp_path / "social.jsonl"
    log = SocialLog(path=p)
    log.write(run_id="r1", kind="post", payload={"agent": "A"})
    log2 = SocialLog(path=p)
    assert log2.chain_integrity()
    assert log2.events()[0].seq == 1


def test_affect_models():
    st = CircumplexState()
    st.tune(target_v=0.5, target_a=0.3, rate=0.5)
    assert st.v == pytest.approx(0.25)
    eff = act_lite_step(st, action_effectiveness=-0.8, action_valence=0.2)
    assert eff < 0
    assert st.v < 0.25 and st.a > 0.3  # failure → negativity + arousal (rumination)

    pad = PADState(pleasure=0.5, arousal=0.4, power=0.2)
    circ = pad_to_circumplex(pad)
    assert 0 <= circ.v <= 1

    st2 = CircumplexState()
    event_appraisal(st2, 0.8, 0.9)
    assert st2.v > 0.1


def test_memory_alliance_formation():
    store = InMemoryMemoryStore()
    for _ in range(8):
        store.observe("A", {"kind": "reply", "payload": {"agent": "B", "content": "sure"}})
    assert store.edge_weight("A", "B") == 8.0
    alliances = list(store.alliances())
    assert alliances[0].formed
    obs = store.recall("A", k=2)
    assert obs[0].content["actor"] == "B"


def test_presence_policy_prunes_and_costs():
    meter = CostMeter("pr")
    policy = PresencePolicy(cost_meter=meter, prune_threshold=-0.1)
    quiet = AgentPresence(id="quiet", pressure=0.0, inhibition=2.0, motivation=0.0)
    active = AgentPresence(id="active", pressure=2.0, inhibition=0.0, motivation=0.8)
    assert policy.prune(quiet) is True
    assert policy.prune(active) is False
    policy.record_move(active)
    assert meter.summarize().total_agents == 1