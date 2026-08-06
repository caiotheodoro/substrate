"""A-S-27 affect-models: Russell circumplex (2D) + PAD + ACT-lite updates.

Synthetic, dependency-light companions to the presence core:
- CircumplexState(v,a): the raw emotion in Russell space.
- PAD: {pleasure, arousal, dominance}, buildable from the circumplex.
- act_lite_step: appraisal-of-consequence update (ACT-lite: action →
  consequence → affect shift with decay toward neutral).

All rules are deterministic; randomness lives in the presence core.
"""

from __future__ import annotations

import numpy as np

NEUTRAL = (0.0, 0.0)


class CircumplexState:
    """Russell circumplex: valence & arousal, each in [-1, 1]."""

    def __init__(self, valence: float = 0.0, arousal: float = 0.0):
        self.v = float(np.clip(valence, -1, 1))
        self.a = float(np.clip(arousal, -1, 1))

    def clone(self) -> "CircumplexState":
        return CircumplexState(self.v, self.a)

    def distance(self, other: "CircumplexState") -> float:
        return float(np.hypot(self.v - other.v, self.a - other.a))

    def tune(self, target_v: float = 0.0, target_a: float = 0.0, rate: float = 0.3, decay: float = 0.05) -> None:
        """Move toward `target`; additionally decay toward neutral."""
        v = self.v + rate * (target_v - self.v) + decay * (0.0 - self.v)
        a = self.a + rate * (target_a - self.a) + decay * (0.0 - self.a)
        self.v = float(np.clip(v, -1, 1)); self.a = float(np.clip(a, -1, 1))


class PADState:
    """Pleasure-Arousal-Dominance in [-1,1]^3."""

    def __init__(self, pleasure=0.0, arousal=0.0, power=0.0):
        self.p = float(np.clip(pleasure, -1, 1))
        self.a = float(np.clip(arousal, -1, 1))
        self.d = float(np.clip(power, -1, 1))


def pad_to_circumplex(pad: PADState) -> CircumplexState:
    """PAD → circumplex (documented approximation: pleasure≈valence,
    arousal≈arousal, dominance modulates the diagonal)."""
    tilt = pad.d * 0.2
    return CircumplexState(
        valence=float(np.clip(pad.p + tilt, -1, 1)),
        arousal=float(np.clip(pad.a, -1, 1)),
    )


def event_appraisal(state: CircumplexState, event_valence: float, event_intensity: float, rate: float = 0.3) -> None:
    """Appraise an event: valence sign sets the move target; intensity, its rate."""
    state.tune(
        target_v=float(np.clip(event_valence, -1, 1)),
        target_a=float(np.clip(event_intensity, 0, 1) + event_intensity * 0.0),
        rate=rate,
    )


def act_lite_step(
    state: CircumplexState,
    action_effectiveness: float,
    action_valence: float,
    rate: float = 0.4,
) -> float:
    """ACT-lite: act on a consequence sign.

    Returns the action's induced arousal/dominance shift. Positive outcome →
    approach (valence up, dominance up); failed outcome → withdrawal (arousal
    up with negative valence — the classic negativity dominance).
    """
    effect = float(np.clip(action_effectiveness, -1, 1))
    if effect >= 0:
        state.tune(target_v=float(np.clip(action_valence + 0.3 * effect, -1, 1)), target_a=0.0, rate=rate)
    else:
        state.tune(target_v=-0.4, target_a=0.5, rate=rate * 1.4)
    return effect