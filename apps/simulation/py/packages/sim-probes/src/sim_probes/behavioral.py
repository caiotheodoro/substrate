"""A-S-31 — behavioral believability probes.

All probes are deterministic (seeded) and consume a C1-style event stream
or a SocialLog, never an LLM. Each probe is a protocol → measurement → bound
check; bounds live in the probe definitions below.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass
class ProbeResult:
    probe: str
    measured: float
    bound: tuple[float, float] | float
    passed: bool
    note: str = ""


@dataclass(frozen=True)
class _ProbeDef:
    name: str
    lower: float
    upper: float


def _check(name: str, value: float, lo: float, hi: float, note: str = "") -> ProbeResult:
    return ProbeResult(probe=name, measured=round(value, 4), bound=(lo, hi), passed=lo <= value <= hi, note=note)


def _event_kinds(events: Sequence[object]) -> list[str]:
    kinds = []
    for e in events:
        kind = getattr(e, "kind", None)
        if kind is None:
            kind = e.get("kind") if isinstance(e, dict) else None
        if kind:
            kinds.append(str(kind))
    return kinds


def lurking_rate(events: Sequence[object], total_rounds: int) -> float:
    """Fraction of rounds where an agent present in the room produced no
    event of its own (lurking). A nonzero lurking rate is expected for
    inhibited agents."""
    if total_rounds <= 0:
        return 0.0
    kinds = _event_kinds(events)
    silent = sum(1 for k in kinds if k in {"silence", "pass", "none"})
    return silent / total_rounds


def interruption_rate(events: Sequence[object]) -> float:
    """Fraction of `post`-kind events that occur within 1 round of a prior
    event by another agent (turn collision). Bound: humans interrupt; agents
    shouldn't constantly interrupt."""
    kinds = _event_kinds(events)
    if not kinds:
        return 0.0
    posts = [i for i, k in enumerate(kinds) if k == "post"]
    if not posts:
        return 0.0
    interruptions = sum(1 for i in posts[1:] if i - posts[posts.index(i) - 1] == 1 and i - posts[posts.index(i) - 1] > 0)
    return interruptions / len(posts)


def latency_distribution(events: Sequence[object]) -> tuple[float, float]:
    """Mean and p95 gap (in rounds) between consecutive events of the same
    agent. Slow-but-responsive beats constant-tick for believability.
    Uses payload `t` (round clock) when present, else event index gaps."""
    by_agent: dict[str, list[float]] = {}
    for i, e in enumerate(events):
        agent = getattr(e, "agent_id", None)
        if agent is None and isinstance(e, dict):
            agent = e.get("payload", {}).get("agent") or e.get("agent")
        if agent is None:
            agent = getattr(e, "payload", {}).get("agent")
        payload = getattr(e, "payload", None)
        t = payload.get("t") if isinstance(payload, dict) else None
        if t is None and isinstance(e, dict):
            t = e.get("payload", {}).get("t")
        by_agent.setdefault(str(agent), []).append(float(i if t is None else t))
    gaps = []
    for ts in by_agent.values():
        gaps.extend(b - a for a, b in zip(ts, ts[1:]))
    if not gaps:
        return 0.0, 0.0
    return float(np.mean(gaps)), float(np.percentile(gaps, 95))


def silence_misreading_rate(events: Sequence[object]) -> float:
    """Fraction of silence events that are immediately followed (<=2 rounds)
    by a confrontation or dismissal — i.e. the room misreads the silence.
    For an uninhibited room this is bounded low."""
    kinds = _event_kinds(events)
    if not kinds:
        return 0.0
    misread = 0
    silences = [i for i, k in enumerate(kinds) if k == "silence"]
    for i in silences:
        for j in range(i + 1, min(i + 3, len(kinds))):
            if kinds[j] in {"dismiss", "confront", "rebuke"}:
                misread += 1
                break
    return misread / max(len(silences), 1)


def alliance_rate(events: Sequence[object]) -> float:
    """Fraction of events where two agents side together (kind `ally`, or
    `reply` targeting the previous speaker repeatedly). Bounded: alliances
    exist but shouldn't dominate."""
    kinds = _event_kinds(events)
    if not kinds:
        return 0.0
    allies = sum(1 for k in kinds if k == "ally")
    return allies / len(kinds)


def run_all_probes(events: Sequence[object], total_rounds: int = 0) -> list[ProbeResult]:
    """Run the five A-S-31 behavioral probes over an event stream."""
    lat_mean, lat_p95 = latency_distribution(events)
    return [
        _check("latency-mean", lat_mean, 0.0, 10.0),
        _check("latency-p95", lat_p95, 0.0, 20.0),
        _check("lurking", lurking_rate(events, total_rounds), 0.0, 0.4),
        _check("interruption", interruption_rate(events), 0.0, 0.25),
        _check("silence-misreading", silence_misreading_rate(events), 0.0, 0.15),
        _check("alliance", alliance_rate(events), 0.0, 0.5),
    ]


def _demo_events(n: int, seed: int = 7) -> list[dict]:
    """Deterministic fake event stream for tests/demos — never an LLM.
    Shaped to human-like behavior: no two `post`s adjacent (no constant
    interruption), occasional silence from one agent."""
    rng = np.random.default_rng(seed)
    agents = ["A", "B", "C"]
    events = []
    t = 0
    last_was_post = False
    for _ in range(n):
        agent = agents[int(rng.integers(0, 3))]
        if last_was_post:
            kind = "reply"
        else:
            kind = "reply" if rng.random() < 0.6 else "post"
        events.append({"kind": kind, "payload": {"agent": agent, "t": t}})
        last_was_post = kind == "post"
        t += 1
    events[0] = {"kind": "post", "payload": {"agent": "A", "t": 0}}
    if len(events) > 1:
        events[1] = {"kind": "reply", "payload": {"agent": "B", "t": 1}}
    events[-1] = {"kind": "silence", "payload": {"agent": "B", "t": t}}
    return events
