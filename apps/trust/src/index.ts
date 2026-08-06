// @substrate/trust — one measurement discipline for actions and data.
// Spec: apps/trust/SPEC.md
//
// This unit is Python-first (see BUILD.md §Language): all atoms live in
// apps/trust/py/ (uv workspace). This file stays a stub on purpose — its
// role is to keep the pnpm workspace graph intact (the C5 contract shape it
// would re-export lives in @substrate/substrate, which 01/03 already
// consume). The C5 HTTP contract is served by :8020, not by TS code.
