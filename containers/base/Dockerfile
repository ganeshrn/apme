# syntax=docker/dockerfile:1
# Shared base for all Python APME services.
# Installs core dependencies once; service images inherit via FROM apme-base.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer: only invalidated when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev \
            --extra ai --extra gateway

# Full source; install the project itself (deps already cached).
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ai --extra gateway

ENV PATH="/app/.venv/bin:$PATH"
