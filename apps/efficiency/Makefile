.PHONY: up down replay-ledger mtu e2e-cost quant-honesty delta-bench tco test typecheck build

up:
	docker compose -f apps/efficiency/compose.yaml up -d

down:
	docker compose -f apps/efficiency/compose.yaml down

build:
	pnpm --filter @substrate/efficiency build

test:
	pnpm --filter @substrate/efficiency test

typecheck:
	pnpm --filter @substrate/efficiency typecheck

# Replay harness-recorded runs (fixture when harness goldens are not present) through the ledger.
replay-ledger: build
	node apps/efficiency/dist/ledger/replay-cli.js --file apps/efficiency/src/data/recorded-steps.jsonl --self

# Marginal-token-utility harness → docs/validation/mtu.txt
mtu: build
	node apps/efficiency/dist/mtu/mtu-report.js apps/efficiency/docs/validation/mtu.txt

# Headline benchmark: baseline vs routed vs cached vs delta (writes the TCO workload fixture)
e2e-cost: build
	node apps/efficiency/dist/bench/e2e-cost-bench.js

quant-honesty: build
	node apps/efficiency/dist/bench/quant-honesty-bench.js 2000

delta-bench: build
	node apps/efficiency/dist/bench/delta-100th-turn-bench.js 100

# TCO: predict current config, or validate against an actual bill: make tco validate ACTUAL=12.34
ACTUAL ?= 12.34
tco: build
	node apps/efficiency/dist/tco/tco-cli.js grid
	node apps/efficiency/dist/tco/tco-cli.js validate --actual $(ACTUAL)
