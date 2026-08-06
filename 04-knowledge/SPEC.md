# 04 · Knowledge — Operating Retrieval Like It's a Database

## Thesis

RAG exploded, then GraphRAG got hype and skepticism from the same people at different points in their experience. Both are justified — the answer reduces to a **specific structural property of the retrieval task**. But nobody has built the ops layer: the extraction-quality evals, entity resolution, freshness management, and retrieval-grounded gates that make a retrieval system **operable** instead of a research artifact.

**Knowledge is retrieval with database discipline.** The same rigor a DBA applies to an OLTP store — schema validation, integrity checks, drift detection, observability — applied to the pipeline that produces what an agent sees.

## Why it matters

Vector RAG is a commodity. GraphRAG is the frontier — and it bought representational power at the cost of operational complexity nobody owns:

- Entity extraction is an LLM step that **fails silently**, and its errors propagate into every retrieval that follows.
- Entity resolution (the same company named three ways) is a matching problem with no clean ground truth at scale.
- The graph goes stale the moment the source corpus changes — freshness is a *retrieval-quality* problem, not a storage problem.
- There is no standard for "how good is this graph's extraction" or "did this answer come from a graph that's actually about the query."

The market sells demo quality; nobody sells operated quality.

## Core concept

### The structural property test

GraphRAG is justified only when your retrieval task has a structural property vector search can't express: multi-hop relational questions ("all suppliers between X and Y"), aggregated entities, contradictory corpus ("who says what, with which stance"). When the task is passage-level semantic similarity, a graph is added complexity for nothing.

The first deliverable is a **decision tool**: characterize a corpus against these structural properties and get an honest "vector / vector+graph / graph-only" answer — with measurable tests, not vibes.

### The ops planes

| Plane | What's operated | Quality mechanism |
|---|---|---|
| Extraction | entities, relations, properties from documents | precision/recall evals on labeled slices; type-constrained schemas |
| Resolution | entity dedup / canonical naming | blocking keys, similarity scoring, human-confirmation queue |
| Assembly | graph structure, ontology alignment | connectivity checks, density/perimeter monitors |
| Lifecycle | ingestion, re-run, deletes, versioning | freshness gates, impact analysis on downstream retrieval |
| Retrieval | query → subgraph → evidence | retrieval-grounded gates (support/contradiction/silent) |

### Grounded retrieval as the trust surface

Every retrieval that feeds an agent decision carries a verdict: does the returned evidence **support**, **contradict**, or stay **silent** on the claim being made? This is the three-state judgment from 02, applied where the evidence is produced — before it ever reaches the agent. A subgraph that contradicts the query should never reach the context window.

## Ecosystem role

- **Consumes from 01:** which decisions actually used retrieval, and whether they later proved right or wrong (the decision log gives the outcome labels for retrieval-quality studies).
- **Feeds to 02:** support/contradiction/silent verdicts per retrieval — the cheapest outside-the-model evidence that exists at scale.
- **Feeds to 03:** retrieval token budgets and cache behavior of context assembly (retrieval results are wire traffic too).
- **Feeds to 05:** corpus properties and extraction quality as input dimensions for simulation worlds built from documents.

## What gets built

1. **Task characterization tool** — the honest GraphRAG-justification questionnaire, with measurable tests for multi-hop/contradiction/stance structure.
2. **Extraction eval harness** — labeled project slices, round-trip validation (extract → re-embed → verify relations), type-constrained extraction to kill category errors; continuous score as corpus grows.
3. **Entity resolution** — blocking + similarity + human-confirmation queue for low-confidence merges (the Harness escalation philosophy from 01: humans only on the uncertain edge).
4. **Freshness gate** — drift monitor between source and graph (what changed upstream, what's now missing/stale) triggering targeted re-ingestion instead of full rebuilds.
5. **Retrieval-grounded gate** — subgraph validated for support/contradiction/silence before evidence is handed to the agent.
6. **Graph observability** — entity coverage per source, relation density, orphan-cluster drift, retrieval support rate over time.

## Architecture sketch

```
sources (docs, DBs, feeds)
   ├─ extraction (type-constrained, LLM-backed) ── round-trip evals
   ├─ entity resolution ── human queue at ambiguity
   ├─ graph assembler
   ├─ freshness monitor ←── source change detection
   └─ graph store (Pinecone/Weaviate/pgvector hybrid)
              ▼
      query → subgraph → grounded-gate verdict (02) → agent context (01)
```

## Research program

- **R1: When is the graph worth it?** A measurement study on corpus properties that *predict* whether graph-backed retrieval beats flat-index at equal cost. The centerpiece: a decision rule teams can run on their own corpus.
- **R2: Extraction-error propagation.** If extraction is x% wrong on entities and y% on relations, what fraction of correct queries still resolves to correct evidence? At what error rate does the graph become a *negative* — worse than naive text retrieval?
- **R3: Freshness economics.** What does stale-upstream cost in retrieval quality vs the cost of re-ingest? Where's the re-merge trigger that pays for itself?
- **R4: Canonicalization calibration.** Entity-resolution quality measured like calibration (precision at ambiguity bands) so the human-queue threshold is a designed decision, not a guess.
- **R5: Grounded-gate effectiveness.** Does support/contradiction gating measurably cut retrieval-borne errors in agent decisions, vs an ungated flat-index baseline?

## Risks / failure modes

- **Graphs as craft, not ops.** A gorgeous ontology is not a system; the value is in the monitors, gates, and drift mechanisms.
- **The eval trap.** Extraction evals on labeled slices are themselves labeled by LLMs — synthetic-ground-truth land (see 02's contamination concerns). Keep real documents in the loops.
- **Task-misjustification.** Teams that should never have built a graph building one anyway; the characterization gate must be opinionated enough to refuse.
- **The grounded-gate gap.** When retrieval is the *only* source (no tool, no schema), silence verdicts dominate — R2's verifiability-gap discipline applies here too.

## Success signals

- A published decision rule for "vector vs graph vs hybrid" with data behind it.
- A retrieval pipeline where extraction error is *visible and decreasing*, freshness is held by gates, and evidence is grounded-checked — an operator, not a dashboard.
- At least one workload where the grounded gate caught a retrieval failure a flat index would have shipped.
- The extraction-error propagation curve (R2) is measured, not hand-waved.