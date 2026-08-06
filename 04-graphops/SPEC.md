# 04 · GraphOps — Operating GraphRAG Like It's a System

## Thesis

RAG exploded, then GraphRAG got hype and skepticism from the same people at different points in their experience. Both are justified — the question reduces to a **specific structural property of the retrieval task**. But nobody has built the *ops layer*: the extraction-quality evals, entity resolution, freshness management, and retrieval-grounded gates that make a GraphRAG **operable** instead of a research artifact.

GraphOps is the operations layer that graph-backed retrieval was always missing.

## Why it matters

Vector RAG is now a commodity; GraphRAG is the frontier of the frontier. But GraphRAG bought its representational power at the cost of operational complexity nobody owns:

- Entity extraction is an LLM step — it **can be wrong, silently**, and its errors propagate into every retrieval that follows.
- Entity resolution (the same company named three ways) is a matching problem with no clean ground truth at scale.
- The graph goes stale the moment the source corpus changes; freshness is a *retrieval-quality* problem, not a storage problem.
- There is no standard for "how good is this graph's extraction" or "did this retrieval answer come out of a graph that's actually about the query".

The market sells *demo quality*; no one sells *operated quality*. That gap is GraphOps.

## Core concept

GraphRAG is justified only when your retrieval task has a structural property vector search can't express — multi-hop relational questions, aggregated entities ("all suppliers between X and Y"), contradictory corpus ("who says what, with which stance"). When the task is *passage-level semantic similarity*, GraphRAG is added complexity for nothing.

So the first deliverable of GraphOps is a **decision tool**: characterize your retrieval task against these structural properties, and get an honest "vector / vector+graph / graph-only" answer.

Then, the ops stack — the same discipline as any database, applied to the extraction step:

| Plane | What's operated | Quality mechanism |
|---|---|---|
| Extraction | entities, relations, properties out of documents | precision/recall evals on labeled slices; type-constrained schemas |
| Resolution | entity dedup / canonical naming | blocking keys, similarity scoring, human-confirmation queue |
| Assembly | graph structure, ontology alignment | connectivity checks, density/perimeter monitors |
| Lifecycle | ingestion, re-run, deletes, versioning | freshness gates, impact analysis on downstream retrieval |
| Retrieval | query → subgraph → evidence | retrieval-grounded gates (see 02 three-state support/contradiction) |

## What gets built

1. **Task characterization tool** — the honest GraphRAG-justification questionnaire, with measurable tests for multi-hop/contradiction/stance structure in a corpus.
2. **Extraction eval harness** — labeled project slices, round-trip validation (extract → re-embed → verify relations), type-constrained extraction to kill category errors; continuous score over time as corpus grows.
3. **Entity resolution for people/places/things** — blocking + similarity + a human confirmation queue for low-confidence merges; works with the GateOS escalation queue (01) philosophy, humans only on the uncertain edge.
4. **Freshness gate** — a monitor that detects drift between source and graph (what changed upstream, what's now missing/stale in the graph) and triggers targeted re-ingestion instead of naive full rebuilds.
5. **Retrieval-grounded gate** — the subgraph returned for a query is validated for support/contradiction before evidence is handed to the agent (pairs with 02).
6. **Graph observability** — the dashboards and invariants that tell you a graph is healthy: entity coverage per source, relation density, no orphan-cluster drift, retrieval support rate over time.

## Architecture sketch

```
sources (docs, DBs, feeds)
   ├─ extraction (type-constrained, LLM-backed) ─ evals round-trip
   ├─ entity resolution ── human queue at ambiguity
   ├─ graph assembler
   ├─ freshness monitor ←── source change detection
   └─ graph store (Pinecone/Weaviate/pgvector hybrid)
              ▼
      query → subgraph → retrieval-grounded gate (02) → agent evidence
```

## Research program

- **R1: When is the graph worth it?** A measurement study on corpus properties that *predict* whether graph-backed retrieval beats flat-index retrieval at equal cost. The centerpiece: a decision rule teams can run on their own corpus to get an honest GraphRAG-vs-RAG answer.
- **R2: Extraction-error propagation.** If extraction is x% wrong on entities and y% on relations, what fraction of correct queries still resolves to correct evidence? At what error rate does the graph become a *negative* — worth less than naive text retrieval?
- **R3: Freshness economics.** What does stale-upstream actually cost in retrieval quality vs the cost of re-ingest? Where's the re-merge trigger that pays for itself?
- **R4: Canonicalization calibration.** Entity resolution quality measured like calibration (precision at ambiguity bands) so the human-queue threshold is a P&L decision, not a guess.

## Prior work it builds on

- Blog: *RAG vs. Fine-Tune: The Build Decision* (cost/maintenance-axis framing), *On Retrieval-Augmented Generation, One Year In* (flat-index failures), *What the Graph Actually Adds* (structural property thesis), *On synthetic data* (for extraction evals), *Structured Outputs* (type-constrained extraction).
- Adopt AI: schema-driven structured outputs, validation gates, JSON-Patch idea reuse for retrieval payloads.
- Skills: RAG, GraphRAG, vector databases (Pinecone/Weaviate/pgvector), semantic search and embeddings, structured outputs, evaluation gates, observability, retrieval-grounded gating (02).

## Risks / failure modes

- **Graphs as craft, not ops.** Building a gorgeous ontology and calling it a system — the real value is in the monitors, gates, and drift mechanisms, not the schema art.
- **The eval trap.** Extraction evals on labeled slices are themselves labeled by LLMs; effort collapses into synthetic-ground-truth land (see 09's contamination concerns).
- **Task-misjustification.** Teams that should never have built a graph building one anyway; the characterization gate must be opinionated enough to refuse.

## Success signals

- A published/used decision rule for "vector vs graph vs hybrid" with data behind it.
- A graph pipeline where extraction error is *visible and decreasing*, freshness is held by gates, and retrievals are grounded-checked — not a dashboard, an operator.
- At least one workload where a subgraph gate caught an actual retrieval failure that a flat index would have shipped.