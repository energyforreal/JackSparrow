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

# Install build dependencies for ML libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libgomp1 \
    libopenblas-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies (ML libraries need build tools)
COPY agent/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && \
    pip install --user --no-warn-script-location -r /tmp/requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/home/agent/.local/bin:${PATH}" \
    MODEL_DIR=/app/agent/model_storage \
    MODEL_PATH= \
    AGENT_SYMBOL=BTCUSD \
    AGENT_INTERVAL=15m

WORKDIR /app

# Install runtime dependencies only (no build tools needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libopenblas-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r agent && useradd -r -g agent agent && \
    mkdir -p /app /app/agent/model_storage /logs && \
    chown -R agent:agent /app /logs

# Copy Python dependencies from builder
COPY --from=builder --chown=agent:agent /root/.local /home/agent/.local

# Copy application code - maintain agent directory structure  
COPY --chown=agent:agent agent /app/agent

# Add build metadata labels
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${COMMIT_SHA}" \
      org.opencontainers.image.title="JackSparrow Agent" \
      org.opencontainers.image.description="AI Trading Agent for JackSparrow"

# Switch to non-root user
USER agent

# Agent doesn't expose HTTP port anymore - use agent-api service

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -m agent.healthcheck || exit 1

CMD ["python", "-m", "agent.core.intelligent_agent"]

