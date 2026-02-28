# syntax=docker/dockerfile:1.7

# Build arguments for metadata
ARG BUILD_DATE
ARG VERSION=latest
ARG COMMIT_SHA=unknown

# Stage 1: Dependencies builder
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && \
    pip install --user --no-warn-script-location -r /tmp/requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/home/backend/.local/bin:${PATH}" \
    BACKEND_PORT=8000

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r backend && useradd -r -g backend backend && \
    mkdir -p /app /logs && \
    chown -R backend:backend /app /logs

# Copy Python dependencies from builder
COPY --from=builder --chown=backend:backend /root/.local /home/backend/.local

# Copy application code - maintain backend directory structure
COPY --chown=backend:backend backend /app/backend

# Copy database and utility scripts so they are available inside the container
COPY --chown=backend:backend scripts /app/scripts

# Add build metadata labels
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${COMMIT_SHA}" \
      org.opencontainers.image.title="JackSparrow Backend" \
      org.opencontainers.image.description="FastAPI backend for JackSparrow Trading Agent"

# Switch to non-root user
USER backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${BACKEND_PORT}/api/v1/health || exit 1

CMD ["sh", "-c", "uvicorn backend.api.main:app --host 0.0.0.0 --port ${BACKEND_PORT}"]

