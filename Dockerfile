### --- FRONTEND BUILD STAGE --- ###
FROM node:22-bookworm-slim AS frontend-build

# Enable pnpm via corepack
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app/web

# Build-time environment variables for React
ARG REACT_APP_AZURE_CLIENT_ID
ARG REACT_APP_AZURE_TENANT_ID
ARG REACT_APP_AZURE_SCOPE
ARG REACT_APP_API_DEV_BASE_URL
ARG NODE_ENV=production

ENV REACT_APP_AZURE_CLIENT_ID=$REACT_APP_AZURE_CLIENT_ID
ENV REACT_APP_AZURE_TENANT_ID=$REACT_APP_AZURE_TENANT_ID
ENV REACT_APP_AZURE_SCOPE=$REACT_APP_AZURE_SCOPE
ENV REACT_APP_API_DEV_BASE_URL=$REACT_APP_API_DEV_BASE_URL
ENV NODE_ENV=$NODE_ENV

# Copy package files for better layer caching
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source and build
COPY web/ ./
RUN pnpm run build && rm -rf src node_modules

### --- BACKEND BUILD STAGE --- ###
FROM python:3.13-slim AS backend-build
WORKDIR /app/vehicle

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy only dependency files first for better caching
COPY vehicle/pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy application code
COPY vehicle/ ./

### --- FINAL IMAGE --- ###
FROM python:3.13-slim

# Add labels for better container management
LABEL maintainer="your-email@example.com" \
      description="Agentic Connected Car Platform" \
      version="2.0.0"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Copy Python dependencies from backend-build
COPY --from=backend-build /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=backend-build /usr/local/bin/ /usr/local/bin/

# Copy backend code
COPY --from=backend-build /app/vehicle ./vehicle

# Copy frontend build to backend public folder
COPY --from=frontend-build /app/web/build ./vehicle/public

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Runtime environment variables (can be overridden at runtime)
ENV API_HOST=0.0.0.0 \
    API_PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start FastAPI backend
CMD ["python", "vehicle/main.py"]