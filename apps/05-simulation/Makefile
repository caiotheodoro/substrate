.PHONY: test typecheck run-api run-bench matrix report tvl

# python workspace
.PHONY: sync
sync:
	cd py && uv sync

.PHONY: test
test:
	cd py && uv run pytest

# typescript bridge
.PHONY: typecheck
typecheck:
	pnpm --filter @substrate/simulation typecheck

# services (ports per SPEC: sim-api 8300, probes-human 8301(v2), seed-synth 8302, simbench 8303)
.PHONY: run-api run-seed run-bench
run-api:
	cd py && uv run uvicorn sim_cross.api:app --reload --port 8300
run-seed:
	cd py && uv run uvicorn sim_seed.app:app --reload --port 8302
run-bench:
	cd py && uv run uvicorn sim_bench.app:app --reload --port 8303

.PHONY: matrix
matrix:
	cd py && uv run simbench run --matrix --out out/bench.parquet

.PHONY: probes
probes:
	cd py && uv run python -m sim_probes.cli

.PHONY: docker-up
docker-up:
	docker compose up --build

.PHONY: tv
tv:
	cat docs/TESTING.md 2>/dev/null || echo "no docs/TESTING.md"