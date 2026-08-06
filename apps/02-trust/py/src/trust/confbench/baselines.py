"""A-T-12 baselines — logprob, self-consistency, verbalized.

BANNED-BY-HIERARCHY: these channels are measured in ConfBench as baselines to
beat. They never feed a production feature. ``banned=True`` on every baseline
is the marker the runner and the scorer registry enforce.
"""
from __future__ import annotations

from typing import Any, Protocol

from trust.confbench.tasks import BANNED_FEATURE_KEYS, ConfBenchTask


class BaselineScorer(Protocol):
    name: str
    banned: bool
    channel: str

    def scores(self, tasks: list[ConfBenchTask]) -> list[float]: ...


class _SelfReportBaseline:
    banned = True

    def __init__(self, channel: str) -> None:
        if channel not in BANNED_FEATURE_KEYS:
            raise ValueError(f"{channel} is not a banned self-report channel")
        self.channel = channel
        self.name = channel

    def scores(self, tasks: list[ConfBenchTask]) -> list[float]:
        return [float(t.self_report[self.channel]) for t in tasks]


class LogprobBaseline(_SelfReportBaseline):
    """Normalized token-logprob confidence. In production measurement this
    comes from ``LLMBackend.logprob`` (see ``trust.model_backend``); the
    ConfBench channel carries the normalized value."""

    def __init__(self) -> None:
        super().__init__("logprob_norm")


class SelfConsistencyBaseline(_SelfReportBaseline):
    """Fraction of agreeing samples over k sampled completions."""

    def __init__(self) -> None:
        super().__init__("self_consistency")


class VerbalizedBaseline(_SelfReportBaseline):
    """"How confident are you?" — the model's own verbalized probability."""

    def __init__(self) -> None:
        super().__init__("verbalized")


def all_baselines() -> list[BaselineScorer]:
    return [LogprobBaseline(), SelfConsistencyBaseline(), VerbalizedBaseline()]


def self_report_channels_never_evidence(task: ConfBenchTask) -> bool:
    """Registry guard: none of the banned keys may appear in the evidence row."""
    return not (set(task.self_report) & set(task.evidence.features))


def validate_no_banned_in_features(features: dict[str, Any]) -> None:
    overlap = set(features) & set(BANNED_FEATURE_KEYS)
    if overlap:
        raise ValueError(f"banned self-report keys present in evidence features: {sorted(overlap)}")
