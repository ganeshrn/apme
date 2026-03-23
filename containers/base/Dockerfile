# syntax=docker/dockerfile:1
# Shared base for all Python APME services.
# Installs core dependencies once; service images inherit via FROM apme-base.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer: only invalidated when pyproject.toml or uv.lock change.
# Bind-mounts avoid adding these files as image layers.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev \
            --extra gateway --extra proxy

# Full source; install the project itself (deps already cached).
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra gateway --extra proxy

ENV PATH="/app/.venv/bin:$PATH"
