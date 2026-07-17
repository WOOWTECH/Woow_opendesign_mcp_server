#!/bin/bash
set -e

# Start supergateway with streamableHttp (supports multiple connections)
OD_API_BASE="${OD_API_BASE:-http://open-design-svc:7457}" \
  supergateway \
    --stdio "python /app/od_mcp_server.py" \
    --port "${MCP_SERVER_PORT:-8000}" \
    --outputTransport streamableHttp \
    --healthEndpoint /healthz &
SUPER_PID=$!
echo "[entrypoint] supergateway started (PID $SUPER_PID) - streamableHttp on :${MCP_SERVER_PORT:-8000}/mcp"

# Start uvicorn
uvicorn od_mcp_admin.main:app --host 0.0.0.0 --port "${ADMIN_PORT:-8080}" &
UVICORN_PID=$!
echo "[entrypoint] uvicorn started (PID $UVICORN_PID)"

cleanup() {
    kill $SUPER_PID $UVICORN_PID 2>/dev/null
    exit 1
}
trap cleanup EXIT TERM INT

# Wait for EITHER process to exit — if one dies, kill the other and exit
# so K8s restarts the container.
wait -n $SUPER_PID $UVICORN_PID 2>/dev/null
echo "[entrypoint] a child process exited, shutting down"
cleanup
