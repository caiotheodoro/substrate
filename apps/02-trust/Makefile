# @substrate/trust (02) runbook — mirrors BUILD.md §Runbook.
PY := py
PY_RUN := cd $(PY) && uv run

.PHONY: up migrate confbench train-scorer serve-scorer calibrate gate-data test

up:
	docker compose up -d --build

migrate:
	docker compose exec -T trust-pg psql -U substrate -d substrate -f - < migrations/001_init.sql

confbench:
	$(PY_RUN) python -m trust.research.r1_dominance --out ../../docs/validation
	$(PY_RUN) python -m trust.research.r2_verifiability --out ../../docs/validation

train-scorer:
	$(PY_RUN) python -m trust.scorer.train --data models/confbench_train.jsonl --out models

serve-scorer:
	$(PY_RUN) uvicorn trust.services.scorer_svc:app --host 0.0.0.0 --port 8020

calibrate:
	$(PY_RUN) python -m trust.recalib.scheduler --out models

gate-data:
	$(PY_RUN) python -m trust.gated_data.pipeline --in models/seeds.jsonl --out models/dataset.jsonl

test:
	cd $(PY) && uv sync --all-groups && uv run pytest
