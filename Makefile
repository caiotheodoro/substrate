# @substrate root — aggregate targets (G-08). Per-unit targets live in each
# unit's Makefile; this file wires them + the root compose profiles.
#
#   make test              # all unit test suites (TS + Python)
#   make typecheck         # all TS packages
#   make up profile=trust  # bring up one unit stack (shared atoms included)
#   make validate          # root compose config + full test sweep

.PHONY: up down test typecheck validate config

COMPOSE ?= docker compose
PROFILE ?= harness

up:
	$(COMPOSE) --profile $(PROFILE) up -d --build

down:
	$(COMPOSE) --profile $(PROFILE) down

config:
	$(COMPOSE) --profile $(PROFILE) config

test:
	pnpm -r test
	$(MAKE) -C apps/trust/py test 2>/dev/null || (cd apps/trust/py && uv run pytest)
	(cd apps/knowledge/py && uv sync --all-packages --all-groups && uv run pytest)

typecheck:
	pnpm -r typecheck

validate:
	$(COMPOSE) config -q
	@for p in harness trust efficiency knowledge simulation; do \
		$(COMPOSE) --profile $$p config -q || exit 1; \
	done
	pnpm -r typecheck
	pnpm -r test
	(cd apps/trust/py && uv run pytest)
	(cd apps/knowledge/py && uv run pytest)
	@echo "root validate: all configs + tests green"
