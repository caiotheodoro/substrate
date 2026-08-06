"""M7 — Presence engine.

presence-core (A-S-26), affect-models (A-S-27), memory-store (A-S-28),
presence-llm (A-S-29), social-log (A-S-30).

ROOM DISCIPLINE (BUILD integrity rule 3): no global scheduler, no
round-robin. Moves are driven by urgency (priority heap); pressure and
inhibition produce SILENCE as a first-class action.
"""

from .affect_models import CircumplexState, PADState, act_lite_step, event_appraisal, pad_to_circumplex
from .presence_core import AgentPresence, AttentionField, PresenceRoom
from .memory_store import DuckDBMemoryStore, InMemoryMemoryStore, MemoryStore
from .social_log import C1StreamEvent, SocialLog
from .presence_llm import PresencePolicy

__all__ = [
    "CircumplexState",
    "PADState",
    "act_lite_step",
    "event_appraisal",
    "pad_to_circumplex",
    "AgentPresence",
    "AttentionField",
    "PresenceRoom",
    "MemoryStore",
    "InMemoryMemoryStore",
    "DuckDBMemoryStore",
    "C1StreamEvent",
    "SocialLog",
    "PresencePolicy",
]