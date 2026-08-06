"""A-S-35 cost-meter: per-agent per-round ledger with pruning + slice-and-scale
hooks. FROM PLAN C4: token buckets are EXCLUSIVE — cachedInputTokens never
overlap inputTokens."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable


@dataclass
class CostLedgerEntry:
    run_id: str
    agent_id: str
    round_idx: int
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    latency_ms: int = 0
    provider: str = "ollama"

    @property
    def total_tokens(self) -> int:
        """Exclusive buckets: cached tokens counted once, never doubled."""
        return self.input_tokens + self.cached_input_tokens + self.output_tokens


@dataclass
class CostSummary:
    total_input_tokens: int = 0
    total_cached_tokens: int = 0
    total_output_tokens: int = 0
    total_agents: int = 0
    total_rounds: int = 0
    per_agent_tokens: dict[str, int] = field(default_factory=dict)
    per_round_tokens: dict[int, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_cached_tokens + self.total_output_tokens


class CostMeter:
    def __init__(self, run_id: str = "run"):
        self.run_id = run_id
        self._entries: list[CostLedgerEntry] = []

    def record(
        self,
        agent_id: str,
        round_idx: int,
        model: str,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        provider: str = "ollama",
    ) -> CostLedgerEntry:
        entry = CostLedgerEntry(
            run_id=self.run_id,
            agent_id=agent_id,
            round_idx=round_idx,
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            provider=provider,
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> list[CostLedgerEntry]:
        return list(self._entries)

    def summarize(self) -> CostSummary:
        s = CostSummary()
        for e in self._entries:
            s.total_input_tokens += e.input_tokens
            s.total_cached_tokens += e.cached_input_tokens
            s.total_output_tokens += e.output_tokens
            s.total_agents = max(s.total_agents, len({x.agent_id for x in self._entries}))
            s.total_rounds = max(s.total_rounds, len({x.round_idx for x in self._entries}))
            s.per_agent_tokens[e.agent_id] = s.per_agent_tokens.get(e.agent_id, 0) + e.total_tokens
            s.per_round_tokens[e.round_idx] = s.per_round_tokens.get(e.round_idx, 0) + e.total_tokens
        return s

    def to_c4_rows(self):
        """Emit rows conforming to C4 StepRecordSchema field names."""
        return [asdict(e) for e in self._entries]


CostCeiling = Callable[[CostSummary], float]