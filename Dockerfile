# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Supergateway
FROM node:22-slim AS node-base
RUN npm install -g supergateway

# Stage 3: Python runtime
FROM python:3.12-slim

# Copy Node.js runtime + supergateway
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=node-base /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/supergateway/dist/index.js /usr/local/bin/supergateway-js || true
RUN echo '#!/bin/sh\nexec /usr/local/bin/node /usr/local/lib/node_modules/supergateway/dist/index.js "$@"' > /usr/local/bin/supergateway && chmod +x /usr/local/bin/supergateway

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl bash && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
WORKDIR /app
RUN pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic python-multipart \
    sse-starlette pyjwt pyyaml aiofiles "mcp[server]"

# Copy source
COPY mcp_admin_core/ ./mcp_admin_core/
COPY od_mcp_admin/ ./od_mcp_admin/
COPY od_mcp_server.py ./

# Copy pre-built frontend as static files (SPA served by FastAPI)
COPY --from=frontend /build/dist/ ./static/

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN mkdir -p /data

ENV PYTHONPATH=/app
EXPOSE 8080 8000

CMD ["/app/entrypoint.sh"]
