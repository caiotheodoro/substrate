# Micro-Adapter Loop — Research RFC (Tier C, evolve of r5/gated-data)

> Source: *From weeks to a day* (Saberidokht, Airbnb Tech Blog, Jul 2026),
> Layer 3: bounded, scoped model mutation. This is the design; the working
> seed lives in `apps/02-trust/py/src/trust/gated_data/micro_patch.py`.

## The idea

A **micro adapter** is a small correction patch (their world: LoRA rank < 50
on a frozen base; ours: any small, scoped candidate model/policy change)
that ships like a software hotfix — scoped to ONE issue, validated behind
TWO gates, canary-deployed with automatic rollback, same-day turnaround.

The article's boundary evidence: Meng et al. (NeurIPS 2022) — factual
behavior is partially localized; Cohen et al. (TACL 2024) — even precise
edits ripple; Pletenev et al. (2025) — LoRA adapters absorb targeted
corrections reliably only up to ~a few hundred examples, beyond which
reasoning degrades.

## The two gates (mapped onto our stack)

1. **No-regression gate** — the patch must not regress expert-reviewed
   domains. Seed: `evaluate_domains(candidate, domains, incumbent)` scores
   every expert-reviewed domain (ConfBench holdout / golden slices) and
   requires per-domain accuracy ≥ incumbent. ConfBench's `ScorerEval`
   (Brier-based) is the accuracy proxy.
2. **Uncertainty gate** — high-uncertainty outputs (judge variance ≥
   threshold, per B2's epistemic/aleatoric decomposition) are flagged for
   **human review** instead of shipping. Seed: `flag_uncertain(...)`
   routes them to 02's label-quality queue (A-T-24).

A patch passes **both** gates → released to a canary lane (01's escalation
band / budget gate): an anomaly rolls it back (blow = decision, never a
crash — already wired in the C4 joint).

## Lifecycle rules (CACE, Sculley et al. 2015)

- **Fuse co-triggering patches** — patches firing on overlapping inputs
  share relational neighborhoods; learnable fusion resolves subspace
  interference. Seed: `PatchLifecycle.fusion_candidates(min_co_triggers)`.
- **Retrain on accumulation** — patches against one category approaching
  the empirical ceiling (Pletenev: ~few hundred; seed constant
  `MAX_PATCHES_PER_CATEGORY = 200`) fold into a clean retrain. Seed:
  `PatchLifecycle.needs_retrain(category)`.
- **Unload unused patches** — patches not triggered in a window are
  unloaded; every loaded patch needs revalidation when upstream changes.
  Seed: `PatchLifecycle.unload_unused(stale_after_days)`.

## Research questions this evolves (r5 → r6)

1. At equal budget, does a gated *patch stack* beat one big retrain on the
   same corrections? (r5's question, now per-patch.)
2. Does the two-gate discipline measurably cut confidently-wrong outputs
   vs single-gate gated-data? (r4's trap-injection, applied to patches.)
3. What is the real Pletenev ceiling for our task families, and where does
   fusion vs retrain cross over? (measured, not assumed.)

## Validation path (v1 seed → measured claim)

```
make train-scorer            # incumbent
make calibrate               # band drift baseline
knowctl calibrate            # judge agreement baseline (B1)
uv run python - <<'EOF'
from trust.gated_data.micro_patch import decide_micro_patch, PatchLifecycle
# ... two-gate decision on a candidate; lifecycle counters
EOF
```

The seed is unit-tested (`tests/test_micro_patch.py`, 11 tests). The full
adapter training/fusion loop is a v2 research exercise that builds on the
gated-data pipeline (A-T-22..28) and the r1–r5 program.
