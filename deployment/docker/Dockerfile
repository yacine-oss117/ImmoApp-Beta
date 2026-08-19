# Stage 1: Builder
FROM python:3.14-slim AS builder

WORKDIR /app

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
# We use requirements/server.txt as seen in the existing file
COPY requirements/server.txt requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt


# Stage 2: Final
FROM python:3.14-slim

ARG IMMOAPP_SOURCE_COMMIT_SHA=""
LABEL org.opencontainers.image.revision="${IMMOAPP_SOURCE_COMMIT_SHA}"

WORKDIR /app

# Create a fixed non-root identity (stable across hosts/volumes)
RUN addgroup --system --gid 10001 appgroup \
    && adduser --system --uid 10001 --ingroup appgroup appuser

# Install runtime dependencies (libpq for Postgres)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

RUN pip install --no-cache /wheels/*

# Copy project configuration
COPY . .

# Stamp the image with the product backend source identity produced from the
# copied checkout. Desktop E2E refuses image-mode backends without this marker.
RUN python -c "from pathlib import Path; from server.services.e2e_control import write_build_identity; write_build_identity(Path('/app'))"

# Prepare writable runtime dir for app data/cache/media/static.
RUN mkdir -p /var/lib/immoapp/cache /var/lib/immoapp/media /var/lib/immoapp/static

# Change ownership to non-root user
RUN chmod +x /app/deployment/docker/run_web.sh \
    && chown -R appuser:appgroup /app /var/lib/immoapp

# Switch to non-root user
USER appuser

# Expose port (Daphne/Gunicorn usually runs on 8000)
EXPOSE 8000

# Health check (simple TCP check or call the health endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health/ || exit 1

# Default command (Production ASGI)
CMD ["/app/deployment/docker/run_web.sh"]

