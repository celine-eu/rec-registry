# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

# Install OS deps (build tools not strictly required for this set, keep lean)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Copy dependency manifests first for better caching
COPY pyproject.toml README.md ./

# Install deps (no dev deps declared; adjust if you add optional groups)
RUN uv sync --no-editable

# Copy application code
COPY celine ./celine
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "celine.rec_registry.main:app", "--host", "0.0.0.0", "--port", "8000"]
