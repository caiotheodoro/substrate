.PHONY: up down replay-ledger mtu e2e-cost quant-honesty delta-bench tco test typecheck build

up:
	docker compose -f apps/03-efficiency/compose.yaml up -d

down:
	docker compose -f apps/03-efficiency/compose.yaml down

build:
	pnpm --filter @substrate/efficiency build

test:
	pnpm --filter @substrate/efficiency test

typecheck:
	pnpm --filter @substrate/efficiency typecheck

# Replay 01-recorded runs (fixture when 01 goldens are not present) through the ledger.
replay-ledger: build
	node apps/03-efficiency/dist/ledger/replay-cli.js --file apps/03-efficiency/src/data/recorded-steps.jsonl --self

# Marginal-token-utility harness → docs/validation/mtu.txt
mtu: build
	node apps/03-efficiency/dist/mtu/mtu-report.js apps/03-efficiency/docs/validation/mtu.txt

# Headline benchmark: baseline vs routed vs cached vs delta (writes the TCO workload fixture)
e2e-cost: build
	node apps/03-efficiency/dist/bench/e2e-cost-bench.js

quant-honesty: build
	node apps/03-efficiency/dist/bench/quant-honesty-bench.js 2000

delta-bench: build
	node apps/03-efficiency/dist/bench/delta-100th-turn-bench.js 100

# TCO: predict current config, or validate against an actual bill: make tco validate ACTUAL=12.34
ACTUAL ?= 12.34
tco: build
	node apps/03-efficiency/dist/tco/tco-cli.js grid
	node apps/03-efficiency/dist/tco/tco-cli.js validate --actual $(ACTUAL)
