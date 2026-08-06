"""A-K-02 characterization-decision-api — the honest GraphRAG-justification
questionnaire. Vector / vector+graph / graph-only, with opinionated refusal.

The rule is a documented decision procedure over the profiler's structural
metrics; confidence comes from the margin between measured metrics and the
rule thresholds. The characterization suite (A-K-03) validates this rule
against corpora with known-best architectures.
"""

from __future__ import annotations

from dataclasses import dataclass

from substrate_knowledge.m1_characterization.profiler import CorpusProfile

MIN_DOCS = 6
MIN_ENTITIES = 12
MH_GRAPH = 0.25
MH_GRAPH_ONLY = 0.45
CI_THRESHOLD = 0.12
AG_THRESHOLD = 0.15
VECTOR = "vector"
VECTOR_GRAPH = "vector+graph"
GRAPH_ONLY = "graph-only"


@dataclass
class CharacterizationVerdict:
    architecture: str  # vector | vector+graph | graph-only
    confidence: float
    reason: str
    refusal: str | None = None  # set ⇒ opinionated refusal, architecture may be null
    profile: dict | None = None

    def to_dict(self) -> dict:
        return {
            "architecture": self.architecture,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "refusal": self.refusal,
            "profile": self.profile,
        }


class DecisionRule:
    """Deterministic rule, frozen for v1. Thresholds are data-tuned in the
    characterization suite (A-K-03) and recorded as benchmarks."""

    def decide(self, profile: CorpusProfile) -> CharacterizationVerdict:
        if profile.n_docs < MIN_DOCS or profile.n_entities < MIN_ENTITIES:
            return CharacterizationVerdict(
                architecture=VECTOR,
                confidence=0.0,
                reason="corpus too small to characterize",
                refusal=(
                    f"corpus too small to characterize ({profile.n_docs} docs, "
                    f"{profile.n_entities} entities); need ≥{MIN_DOCS} docs and ≥{MIN_ENTITIES} "
                    f"entities. Run the characterization-suite (A-K-03) once the corpus grows."
                ),
                profile=profile.to_dict(),
            )

        mh = profile.multi_hop_index
        ci = profile.contradiction_index
        ag = profile.aggregation_share
        profile_dict = profile.to_dict()

        needs_graph = mh >= MH_GRAPH or ci >= CI_THRESHOLD or ag >= AG_THRESHOLD
        if not needs_graph:
            conf = 0.5 + 0.5 * (1.0 - max(mh, ci, ag) / max(MH_GRAPH, CI_THRESHOLD, AG_THRESHOLD))
            return CharacterizationVerdict(
                architecture=VECTOR,
                confidence=min(conf, 0.98),
                reason=(
                    f"no structural signal: multi-hop reachability {mh:.2f} (<{MH_GRAPH}), "
                    f"contradiction {ci:.2f} (<{CI_THRESHOLD}), aggregation {ag:.2f} (<{AG_THRESHOLD}). "
                    f"Passage-level similarity dominates → flat vector index."
                ),
                profile=profile_dict,
            )

        if mh >= MH_GRAPH_ONLY and ci < CI_THRESHOLD and ag < AG_THRESHOLD:
            conf = 0.5 + 0.25 * (mh - MH_GRAPH_ONLY) / (1 - MH_GRAPH_ONLY)
            return CharacterizationVerdict(
                architecture=GRAPH_ONLY,
                confidence=min(conf, 0.95),
                reason=(
                    f"dense relational structure (multi-hop {mh:.2f} ≥ {MH_GRAPH_ONLY}) with no "
                    f"contradiction ({ci:.2f}) and no aggregation ({ag:.2f}) → graph-only."
                ),
                profile=profile_dict,
            )

        reason_parts = []
        if mh >= MH_GRAPH:
            reason_parts.append(f"multi-hop reachability {mh:.2f} ≥ {MH_GRAPH}")
        if ci >= CI_THRESHOLD:
            reason_parts.append(f"contradiction structure {ci:.2f} ≥ {CI_THRESHOLD} (stance provenance needed)")
        if ag >= AG_THRESHOLD:
            reason_parts.append(f"aggregation share {ag:.2f} ≥ {AG_THRESHOLD}")
        margin = max(0.0, max(mh - MH_GRAPH, ci - CI_THRESHOLD, ag - AG_THRESHOLD))
        conf = 0.5 + 0.5 * min(1.0, margin / 0.3)

        if ci >= CI_THRESHOLD and mh < MH_GRAPH_ONLY:
            # opinionated: contradiction tracking needs provenance, but sparse
            # structure still needs passage retrieval → refuse graph-only.
            return CharacterizationVerdict(
                architecture=VECTOR_GRAPH,
                confidence=min(conf, 0.97),
                reason="; ".join(reason_parts)
                + ". Contradiction requires per-document stance provenance → hybrid.",
                profile=profile_dict,
            )
        return CharacterizationVerdict(
            architecture=VECTOR_GRAPH,
            confidence=min(conf, 0.97),
            reason="; ".join(reason_parts) + " → hybrid (graph for joins, vector for passages).",
            profile=profile_dict,
        )
