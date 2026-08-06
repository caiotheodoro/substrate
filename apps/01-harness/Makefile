DATABASE_URL ?= postgres://substrate:substrate@localhost:5432/harness
PORT_API ?= 8930
PORT_GATE ?= 8934
PORT_ESC ?= 8935
PORT_SANDBOX ?= 8936
PORT_DOCK ?= 8938
PORT_WEB ?= 8941

export DATABASE_URL

.PHONY: up down migrate seed record replay golden bench test typecheck api gate escalation sandbox hitl web

up:
	docker compose -f compose.yaml up -d

down:
	docker compose -f compose.yaml down

migrate:
	node --experimental-strip-types src/scripts/migrate.ts

seed:
	node --experimental-strip-types src/scripts/seed.ts

record:
	node --experimental-strip-types src/cli/cli.ts record run-echo
	node --experimental-strip-types src/cli/cli.ts record run-form
	node --experimental-strip-types src/cli/cli.ts record run-gated

replay:
	node --experimental-strip-types src/cli/cli.ts replay run-echo
	node --experimental-strip-types src/cli/cli.ts replay run-form
	node --experimental-strip-types src/cli/cli.ts replay run-gated

golden:
	pnpm test -- --run src/replay/golden.test.ts

bench:
	node --experimental-strip-types src/scripts/bench.ts

test:
	pnpm test

typecheck:
	pnpm typecheck

api:
	node --experimental-strip-types src/scripts/serve-api.ts

gate:
	node --experimental-strip-types src/scripts/serve-gate.ts

escalation:
	node --experimental-strip-types src/scripts/serve-escalation.ts

sandbox:
	node --experimental-strip-types src/scripts/serve-sandbox.ts

hitl:
	node --experimental-strip-types src/scripts/serve-dock.ts

web:
	node --experimental-strip-types src/scripts/serve-web.ts
