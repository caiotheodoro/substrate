FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv pip install --no-deps -e .

EXPOSE 8010 8011 8012 8020 8030 8031 8032 8033 8034 8040 8041
CMD ["uv", "run", "python", "-m", "trust.services.scorer_svc"]
