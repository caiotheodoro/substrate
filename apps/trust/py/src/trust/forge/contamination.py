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
from typing import Any, Callable

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


def format_hint(task: ForgeTask) -> str:
    """The structural hint a leak probe reveals to a surrogate: tool names
    and arg KEYS only, values withheld. If the surrogate fills in the real
    values anyway, it already knew them — that's the Gemini-3 evidence
    (a verification model reproduced ARC's integer-to-color mapping in its
    reasoning chain despite never being told it)."""
    parts = [f"{c.name}({', '.join(sorted(c.args.keys()))})" for c in task.expected]
    return " -> ".join(parts)


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


def build_reference_corpus(n: int, *, index_offset: int = 10_000_000) -> list[ForgeTask]:
    """An independently-generated task pool simulating "content already
    circulating publicly / present in training data" — built from a
    disjoint index range (see ``ToolUseTaskGenerator.generate``'s
    ``index_offset``) so it shares no incidental structure with a normal
    benchmark population. This is what makes ``run_leak_probes`` a real
    detector rather than a tautology: the knowledge base it checks against
    is built from a genuinely separate source, not derived from the same
    task list being tested."""
    from trust.forge.generators import ToolUseTaskGenerator

    return ToolUseTaskGenerator().generate(n=n, index_offset=index_offset)


def inject_leaks(
    tasks: list[ForgeTask],
    reference_corpus: list[ForgeTask],
    *,
    fraction: float,
    seed: int = 0,
) -> tuple[list[ForgeTask], set[str]]:
    """Deliberately make ``fraction`` of ``tasks`` byte-identical (expected
    trajectory + tools) to a task drawn from ``reference_corpus`` —
    simulating benchmark tasks whose exact content has genuinely leaked
    into that external material. Returns the mutated population and the
    set of task_ids that were actually leaked (for ROC bookkeeping); tasks
    not selected are returned unchanged."""
    import dataclasses
    import random

    rng = random.Random(seed)
    n_leak = min(len(tasks), len(reference_corpus), max(0, round(len(tasks) * fraction)))
    leak_positions = set(rng.sample(range(len(tasks)), n_leak)) if n_leak else set()
    ref_pool = list(reference_corpus)
    rng.shuffle(ref_pool)

    mutated: list[ForgeTask] = []
    leaked_ids: set[str] = set()
    for i, t in enumerate(tasks):
        if i in leak_positions and ref_pool:
            src = ref_pool.pop()
            leaked_task = dataclasses.replace(t, expected=src.expected, tools=src.tools)
            mutated.append(leaked_task)
            leaked_ids.add(leaked_task.task_id)
        else:
            mutated.append(t)
    return mutated, leaked_ids


def leaked_knowledge_base(reference_corpus: list[ForgeTask]) -> set[tuple[tuple[tuple[str, str, object], ...]]]:
    """The set of signatures a leak probe checks against — built once from
    an external reference corpus (see ``build_reference_corpus``)."""
    return {format_signature(t) for t in reference_corpus}


def run_leak_probes(
    tasks: list[ForgeTask],
    knowledge_base: set[tuple[tuple[tuple[str, str, object], ...]]],
) -> list[LeakProbe]:
    """For every task, the probe checks whether its FORMAT SIGNATURE
    appears in an INDEPENDENTLY-BUILT knowledge base (``leaked_knowledge_base``
    over ``build_reference_corpus`` / ``inject_leaks``) — not a lookup table
    built from the same population being tested, which would make any
    match on a deliberately-leaked task trivially guaranteed (it would
    just be finding itself). Firing on a task means its exact structural
    content is present in material the probe never saw the task's own
    trajectory come from."""
    probes: list[LeakProbe] = []
    for task in tasks:
        sig = format_signature(task)
        fired = sig in knowledge_base
        probes.append(LeakProbe(probe_id=task.task_id, fired=fired, detail=f"sig_in_kb={fired}"))
    return probes


def _reproduces_value(value: object, completion: str) -> bool:
    """Boundary-aware match, not a bare substring check. Plain
    `str(value) in completion` fires on any digit coincidence — a
    completion mentioning "13" would "reproduce" a value of 3, since "3"
    is a substring of "13". Several mock tools (sum, delay) use small
    plain-integer args, so this isn't a hypothetical.

    A plain regex `\\b...\\b` isn't enough either: this pipeline's other
    common value shape is path-like strings ("/api/1", "/tmp/f3.txt")
    whose own edges are punctuation, not word characters — `\\b` requires
    a word-char/non-word-char transition, and a value preceded by a space
    (non-word) has no such transition on a non-word-starting value, so
    "/api/1" right after a space never matches its own `\\b`. The
    boundary is only meaningful (and only enforced) on whichever side of
    the value is itself alphanumeric; a punctuation-led or -trailed edge
    is already self-delimiting."""
    import re

    s = str(value)
    left = r"(?<![A-Za-z0-9])" if s[:1].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if s[-1:].isalnum() else ""
    pattern = left + re.escape(s) + right
    return re.search(pattern, completion) is not None


def run_llm_leak_probes(
    tasks: list[ForgeTask],
    complete_fn: Callable[[ForgeTask, str], str],
) -> list[LeakProbe]:
    """The real-surrogate leak probe (S4's synthetic version made concrete):
    prompt ``complete_fn`` with only ``format_hint(task)`` — tool names and
    arg keys, no values — and check whether the completion reproduces the
    withheld VALUES anyway. Firing means the surrogate already knew content
    it was never shown: reasoning-chain contamination, not a lucky guess.
    A well-behaved (uncontaminated) surrogate stays silent on every task."""
    probes: list[LeakProbe] = []
    for task in tasks:
        hint = format_hint(task)
        completion = complete_fn(task, hint)
        sig = format_signature(task)[0]
        fired = bool(sig) and all(_reproduces_value(value, completion) for _tool, _key, value in sig)
        # The completion itself (bounded) is logged, not just fired/not —
        # a total network outage and a genuinely honest "I don't know"
        # both produce fired=False, and were previously indistinguishable
        # in the artifact. A bounded prefix here is enough to tell them
        # apart on inspection without bloating the artifact with full
        # model output on every task.
        probes.append(
            LeakProbe(
                probe_id=task.task_id,
                fired=fired,
                detail=f"hint={hint!r} reproduced_values={fired} completion={completion[:200]!r}",
            )
        )
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
    # Explicit set, not a substring match on LeakProbe.detail (the prior
    # version keyed leaked/clean off "leaked=True"/"leaked=False" appearing
    # in a free-text detail string — any change to that string's format
    # would have silently zeroed out both rates below).
    leaked_ids: set[str] = field(default_factory=set)
    corpus_overlap: dict[str, float] = field(default_factory=dict)
    structural_ood: float = 0.0

    @property
    def leaked_fire_rate(self) -> float:
        leaked = [p for p in self.leaks if p.probe_id in self.leaked_ids]
        if not leaked:
            return 0.0
        return sum(1 for p in leaked if p.fired) / len(leaked)

    @property
    def clean_false_fire_rate(self) -> float:
        clean = [p for p in self.leaks if p.probe_id not in self.leaked_ids]
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
    knowledge_base: set[tuple[tuple[tuple[str, str, object], ...]]],
    leaked_ids: set[str],
    corpus_texts: list[str] | None = None,
) -> ContaminationReport:
    """``knowledge_base`` must be built independently of ``tasks`` (see
    ``build_reference_corpus`` + ``leaked_knowledge_base``) and
    ``leaked_ids`` must name which of ``tasks`` were actually leaked into
    it (see ``inject_leaks``) — passing a knowledge base derived from
    ``tasks`` itself turns "fire on leaked" back into a tautological
    self-lookup, which is the bug this signature exists to make hard to
    reintroduce by accident."""
    probes = run_leak_probes(tasks, knowledge_base)
    overlaps = corpus_overlap(tasks, corpus_texts or [])
    ood = structural_ood_score(public, private)
    return ContaminationReport(leaks=probes, leaked_ids=leaked_ids, corpus_overlap=overlaps, structural_ood=ood)
