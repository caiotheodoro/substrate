# 07 · GenUI-Wire — The Wire Format of Generated UI Is the Product

## Thesis

When a model generates UI, the representation matters more than the interface. Most teams got this backwards, either shipping fully-generated components (the LLM producing JSX blind, impossible to gate, impossible to reuse) or fully-static dashboards (null intelligence, no adaptation). **The correct architecture is registry-driven, schema-validated, delta-based generation**: the model never touches pixels; it produces structured payloads against a versioned schema registry, and multi-turn edits ride the wire as JSON-Patch deltas.

GenUI-Wire is the open, testable specification of that wire format.

## Why it matters

The GenUI question is quietly the Gen AI product question: most "AI UI" is a race to the bottom where the model generates components and the UI breaks, adopts a highly variable identity, and no one can gate or track it. Meanwhile the same teams that would *never* let a model emit raw SQL still let it emit raw React. The wire format is the trust boundary: **versioned schema → validated → registry-bound → token-budgeted → exactly-once**. That's the difference between an AI-demo dashboard and an AI *product*.

The economics are the divisible part: the 6-layer token-optimization scheme (≈15k → 700–2k on dashboard prompts) and the JSON-Patch delta (90% token savings on follow-up edits) show the cost of getting this wrong compounds on every single turn.

## Core concept

### Registry over generation

The model doesn't dream up components. The registry knows the components. Client renders a schema-indexed component set; the model selects from a **registry** (constrained structured output against a Zod-codifiable schema registry), and the client resolves and places defined components.

- **Determinism**: same payload → same UI. No brown-blob React.
- **Gateability**: the payload is validated against schema *before* it touches the render path — a structured output + gate point that pairs with 01 and 02.
- **Evolvable**: registry versioning is the product versioning scheme.

### The JSON-Patch delta protocol

Multi-turn edits. First render: full schema payload. Follow-up turns: a sequence of JSON-Patch deltas — *minimal diffs*. On a dashboard:
- first turn ≈ the ~15k-token full prompt and the new downstream payload
- follow-up ≈ one patch (add a card, change an axis, resize) → 90% token savings, and the render path applies patches with validation per patch.

### The 6-layer budget

The system prompt is decomposed into six layers (registry files, schema refs, current state, delta context, render constraint, concise usage rules) each independently cacheable/optimizable (feeds 03 CostOS's prompt-cache analytics).

## What gets built

1. **The wire spec** — versioned; the JSON payload grammar, the schema registry format, patch operation set, error semantics, validation rules. Open, documented, tested.
2. **Open registry** — canonical example catalog: dashboard, table, chart controls, forms, onboarding; each with a corresponding schema.
3. **Reference renderer + validator** — open implementation against the spec (React re-rooted); schema-validated payloads via Zod; patch application with optimistic updates.
4. **GenUI engineering loop** — generation server (offline/SSE), registry-driven structured prompts, the 6-layer prompt builder, prompt-cache-friendly.
5. **Eval & gate integration** — generated payloads run through the 01 gate; a "patched a valid component at the registry constraint" guarantee; snapshot/reflection tests.

## Architecture sketch

```
user/turn ~> classify intent
              │
              ▼
   schema registry (versioned, typed)
              │
              ▼
  LLM assigns structured payload (Zod schema → apply dataclass)
   first turn: full payload | follow-up turn: JSON-Patch deltas
              │
              ▼
        schema.safeParse() ── fail
              │ ✓
        renderer resolves registry components
              │
              ▼
        rendered UI (deterministic) + token accounting (03) 
```

## Research program

- **R1: The convergence of UI *forms*.** What fraction of real dashboard UI can be expressed through a *finite* registry of schemas before you collide with a genuinely-novel shape? The hypothesis: ~80-90% of product UI, and the residual novel shape is exactly the 10% that always ends up custom anyway.
- **R2: Patch-failure semantics.** When a JSON-Patch delta applied against an observed state conflicts (element moved or deleted upstream), what semantics produce the least harmful UX? (rebase → present-the-surface → regenerate-element)
- **R3: Token-everything, measured.** The 6-layer optimization, isolated dollar figures under 03's cost ledger; see the delta real token savings at scale, whether the 90% claim holds at the 100th turn of a session.
- **R4: Generative velocity vs determinism.** After the registry converges, what's left for the "generative" layer to *decide* — layout, hierarchy, emphasis, not raw existence. Map it.

## Prior work it builds on

- Adopt: GenUI architecture (registry-driven, 6-layer token optimization, JSON-Patch delta protocol), the Adopt.AI design system (`gen-ui` repo — schema-driven generative UI components with Zod validation).
- Blog: *On Generative UI* (the wire format is the point, not the design), *Structured Outputs* (schema as trust boundary).
- 01, 03: gating + cost coupling.

## Risks / failure modes

- **Registry entropy.** The registry grows unmaintained → schemas drift → "registry-driven" becomes "very opinionated boilerplate." Mitigate: registry as versioned product artifact; schema-deprecation tooling.
- **Re-base hell.** Patch deltas accumulate in long sessions — eventual inconsistency without a "squash to full state" mechanism. Include in spec: period compaction.
- **Constraint overgrowth.** The 6-layer schema that's so specific the model can't emit anything useful. Hint: measure token-vs-novelty per layer.

## Success signals

- The wire spec stands alone and a non-expert team builds a working adapter against it in a weekend.
- A measured token-consumption per session versus current dashboards published (with the 90% follow-up savings claim reproduced).
- Gate/validated payloads rendered into production: **no payload can render that didn't pass schema validation** (enforced by the renderer).