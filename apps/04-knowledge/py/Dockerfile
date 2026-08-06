# @substrate/knowledge (04) — knowledge API image.
FROM python:3.12-slim

ENV UV_LINK_MODE=copy \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv==0.12.2

WORKDIR /workspace

COPY py/pyproject.toml py/uv.lock ./
COPY py/packages/knowledge/pyproject.toml packages/knowledge/pyproject.toml
COPY py/packages/knowledge/src packages/knowledge/src

# uv 0.12's default `sync` skips workspace members for this layout;
# `--all-packages` installs them explicitly.
RUN uv sync --frozen --all-packages --all-groups
EXPOSE 8201 8202 8203 8204

ENTRYPOINT ["uv", "run"]
