# @substrate/knowledge

**Retrieval operated like a database.** Extraction evals, entity resolution, freshness gates, and grounded retrieval — the ops layer graph-backed retrieval was always missing.

## What it is

RAG is a commodity; GraphRAG is the frontier and it bought representational power at the cost of operational complexity nobody owns. Knowledge applies DBA discipline to the pipeline that produces what an agent sees:

- **Task characterization** — an honest "vector / vector+graph / graph-only" decision rule, from the structural properties of your corpus.
- **Extraction evals** — type-constrained extraction, round-trip validation, continuous score as the corpus grows.
- **Entity resolution** — blocking + similarity + a human-confirmation queue at ambiguity.
- **Freshness gates** — drift detection triggering targeted re-ingestion, not full rebuilds.
- **Grounded retrieval** — every subgraph verdict: support / contradict / silent.

## Benchmarks

- **Graph-vs-flat decision rule** — corpus properties that predict when a graph pays for itself.
- **Extraction-error propagation** — at what error rate does the graph become a *negative*?
- **Freshness economics** — stale-upstream cost vs re-ingest cost.
- **Grounded-gate effectiveness** — does support/contradiction gating measurably cut retrieval-borne errors?

## Ecosystem

- Feeds support/contradiction verdicts (the cheapest outside-the-model evidence) to `trust`.
- Feeds retrieval token/cache behavior to `efficiency`; consumes Harness decision outcomes as retrieval-quality labels.

## State

Implemented. Corpus characterization + decision API (:8201), extraction
pipeline + eval harness with golden slices, entity resolution (:8202),
graph/vector assembly + subgraph extractor (:8203), freshness ledger,
grounded gate (:8204, C3 verdicts) with the judge-calibration loop
(`knowctl calibrate`), and the graph-vs-flat / error-propagation benches.
89 tests.