# @substrate/knowledge (04) — Makefile (ports 8201-8204)
# Local-only stack: infra datastores by default; `make up` adds the APIs.

COMPOSE ?= docker compose
PY ?= cd py && uv run

.PHONY: up down migrate characterize ingest eval-extraction resolve gate bench test lint

up:
	$(COMPOSE) --profile infra --profile llm up -d

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) exec -T knowledge-pg psql -U substrate -d substrate -f - < migrations/0001_knowledge_init.sql

characterize:
	$(PY) knowctl characterize $(CORPUS)

ingest:
	$(PY) knowctl ingest $(DOCS)

eval-extraction:
	$(PY) knowctl eval-extraction

resolve:
	$(PY) knowctl resolve

gate:
	$(PY) knowctl gate --claim "$(CLAIM)" --evidence "$(EVIDENCE)"

bench:
	$(PY) knowctl bench --outdir $(or $(OUTDIR),docs/validation)

test:
	cd py && uv sync --all-packages --all-groups && uv run pytest
