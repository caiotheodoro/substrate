FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

WORKDIR /app

COPY py/pyproject.toml py/pyproject.toml
COPY py/packages ./packages

RUN uv sync --no-install-project --no-dev

COPY py .
COPY packages ./packages

EXPOSE 8300 8302 8303

CMD ["uv", "run", "uvicorn", "sim_cross.api:app", "--host", "0.0.0.0", "--port", "8300"]