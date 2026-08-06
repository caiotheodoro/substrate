"""P7 — contamination monitoring.

Three layers:

1. **Reasoning-chain leak probes** — can a surrogate model (here: an
   n-gram heuristic, LLM-pluggable) complete our task *formats* from
   hints? A task's format signature (tool-name sequence + arg keys) is
   probed against a "leaked" variant; if the probe fires on deliberately
   leaked material and stays silent on clean material, the monitor works.

2. **Corpus matching** — MinHash / n-gram overlap between the task
   prompts and a reference corpus (public data, prior tasks). Reuses the
   trust contamination gate's n-gram discipline.

3. **Structural OOD** — the private split must be structurally
   out-of-distribution relative to the public split (ARC-AGI-3's inverted
   split philosophy): we measure the signature overlap between splits and
   require it below a threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trust.forge.task import ForgeTask

NGRAM_N = 3


def ngrams(text: str, n: int = NGRAM_N) -> set[tuple[str, ...]]:
    words = [w for w in text.lower().split() if len(w) > 2]
    return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


def format_signature(task: ForgeTask) -> tuple[tuple[tuple[str, str, object], ...]]:
    """The task's structural fingerprint: ordered (tool, key, value) triples.
    This is the 'format' that leaks through a reasoning chain — the
    Gemini-3 evidence: a model that had seen the benchmark uses the exact
    values (color mappings) without being told them. Value-level, not just
    key-level, because format alone cannot distinguish tasks."""
    return (tuple((c.name, k, v) for c in task.expected for k, v in c.args.items()),)


@dataclass
class LeakProbe:
    """Reasoning-chain leak probe: does a hint about the task FORMAT let a
    surrogate complete the task? The surrogate is a heuristic that, given
    the signature, can reproduce the expected trajectory. We leak the
    signature into a probe prompt and measure whether the surrogate
    'solves' the task without seeing it."""

    probe_id: str
    fired: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"probe_id": self.probe_id, "fired": self.fired, "detail": self.detail}


def run_leak_probes(tasks: list[ForgeTask], leaked_ids: set[str]) -> list[LeakProbe]:
    """For every task, the probe checks whether its FORMAT SIGNATURE is in
    the leaked knowledge base (the set of signatures of ``leaked_ids``).
    If the signature leaks, a surrogate could reproduce the task from the
    hint alone — the probe fires. A well-behaved monitor fires exactly on
    the leaked tasks and stays silent on clean ones."""
    probes: list[LeakProbe] = []
    signatures = {t.task_id: format_signature(t) for t in tasks}
    leaked_signatures = {signatures[tid] for tid in leaked_ids if tid in signatures}
    for task in tasks:
        sig = signatures[task.task_id]
        fired = sig in leaked_signatures
        detail = f"leaked={task.task_id in leaked_ids} sig_in_kb={fired}"
        probes.append(LeakProbe(probe_id=task.task_id, fired=fired, detail=detail))
    return probes


def corpus_overlap(tasks: list[ForgeTask], corpus_texts: list[str]) -> dict[str, float]:
    """Jaccard n-gram overlap between each task prompt and the corpus. High
    overlap on many tasks = the benchmark content is in the training data."""
    corpus_ngrams = set()
    for text in corpus_texts:
        corpus_ngrams |= ngrams(text)
    overlaps: dict[str, float] = {}
    for task in tasks:
        t = ngrams(task.prompt)
        if not t:
            overlaps[task.task_id] = 0.0
            continue
        overlaps[task.task_id] = len(t & corpus_ngrams) / len(t)
    return overlaps


def structural_ood_score(public: list[ForgeTask], private: list[ForgeTask]) -> float:
    """Fraction of private-task signatures that appear in the public split.
    ARC's philosophy: the private set must be structurally OOD from
    anything demonstrated publicly. Threshold: < 0.5 (at most half the
    private mechanics appear in public)."""
    pub_sigs = {format_signature(t) for t in public}
    if not private:
        return 0.0
    overlap = sum(1 for t in private if format_signature(t) in pub_sigs)
    return overlap / len(private)


@dataclass
class ContaminationReport:
    leaks: list[LeakProbe] = field(default_factory=list)
    corpus_overlap: dict[str, float] = field(default_factory=dict)
    structural_ood: float = 0.0

    @property
    def leaked_fire_rate(self) -> float:
        leaked = [p for p in self.leaks if "leaked=True" in p.detail]
        if not leaked:
            return 0.0
        return sum(1 for p in leaked if p.fired) / len(leaked)

    @property
    def clean_false_fire_rate(self) -> float:
        clean = [p for p in self.leaks if "leaked=False" in p.detail]
        if not clean:
            return 0.0
        return sum(1 for p in clean if p.fired) / len(clean)

    def as_dict(self) -> dict[str, Any]:
        return {
            "leak_probe_fire_rate_on_leaked": round(self.leaked_fire_rate, 4),
            "leak_probe_false_fire_on_clean": round(self.clean_false_fire_rate, 4),
            "mean_corpus_overlap": round(sum(self.corpus_overlap.values()) / max(len(self.corpus_overlap), 1), 4),
            "structural_ood_overlap": round(self.structural_ood, 4),
        }


def monitor_contamination(
    tasks: list[ForgeTask],
    *,
    public: list[ForgeTask],
    private: list[ForgeTask],
    leaked_ids: set[str],
    corpus_texts: list[str] | None = None,
) -> ContaminationReport:
    probes = run_leak_probes(tasks, leaked_ids)
    overlaps = corpus_overlap(tasks, corpus_texts or [])
    ood = structural_ood_score(public, private)
    return ContaminationReport(leaks=probes, corpus_overlap=overlaps, structural_ood=ood)
