"""A-K-29 metrics-exporter.

prom-client is optional: the no-op exporter is the default so tests and
offline runs never depend on it; `get_exporter()` reads `KNOW_METRICS`
(prom | noop, default noop). The gauge names mirror the dashboard panels
(support rate, extraction trend, staleness age, queue depth).
"""

from __future__ import annotations

import os
from typing import Any


class MetricsExporter:
    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None: ...
    def counter_inc(self, name: str, amount: float = 1.0, labels: dict[str, str] | None = None) -> None: ...
    def snapshot(self) -> dict[str, float]: ...


class NoopMetricsExporter(MetricsExporter):
    """Default: nothing recorded, nothing emitted."""

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        return None

    def counter_inc(self, name: str, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        return None

    def snapshot(self) -> dict[str, float]:
        return {}


class PrometheusMetricsExporter(MetricsExporter):
    """prom-client backed; lazy import, constructed only when requested."""

    def __init__(self) -> None:
        try:
            from prometheus_client import Counter, Gauge  # type: ignore

            self._gauges: dict[str, Any] = {}
            self._counters: dict[str, Any] = {}
            self._Gauge = Gauge
            self._Counter = Counter
        except ImportError:
            self._gauges = {}
            self._counters = {}
            self._Gauge = None
            self._Counter = None

    def _gauge(self, name: str) -> Any:
        if name not in self._gauges:
            self._gauges[name] = self._Gauge(name, name) if self._Gauge else None
        return self._gauges[name]

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        gauge = self._gauge(name)
        if gauge is not None:
            gauge.set(value)

    def counter_inc(self, name: str, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        if name not in self._counters:
            self._counters[name] = self._Counter(name, name) if self._Counter else None
        counter = self._counters[name]
        if counter is not None:
            counter.inc(amount)

    def snapshot(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, gauge in self._gauges.items():
            try:
                out[name] = float(gauge._value.get())
            except Exception:
                continue
        return out


def get_exporter() -> MetricsExporter:
    backend = os.environ.get("KNOW_METRICS", "noop")
    if backend == "prom":
        return PrometheusMetricsExporter()
    return NoopMetricsExporter()
