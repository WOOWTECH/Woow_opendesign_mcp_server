"""Connection configuration router for Open Design MCP.

Manages OD daemon connection settings (simple HTTP URL).

Endpoints:
    GET  /api/config            - Current connection config
    PUT  /api/config/connection  - Update daemon URL
    POST /api/config/test        - Test HTTP connectivity to OD daemon
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mcp_admin_core.config import get_config_store
from mcp_admin_core.process import get_process_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

# Allowed URL schemes
_ALLOWED_SCHEMES = {"http", "https"}

# Blocked hostnames — cloud metadata endpoints
_BLOCKED_HOSTS = {
    "169.254.169.254",          # AWS/GCP metadata
    "metadata.google.internal", # GCP metadata
    "100.100.100.200",          # Alibaba metadata
}


def _validate_url_ssrf(url: str) -> None:
    """Reject URLs targeting internal/metadata endpoints (SSRF protection)."""
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise HTTPException(400, f"URL scheme '{parsed.scheme}' not allowed")

    hostname = parsed.hostname or ""

    # Block metadata endpoints
    if hostname in _BLOCKED_HOSTS:
        raise HTTPException(400, "URL targets a blocked metadata endpoint")

    # Block localhost/loopback (except for internal cluster services)
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_loopback:
            raise HTTPException(400, "URL targets loopback address")
        if addr.is_link_local:
            raise HTTPException(400, "URL targets link-local address")
    except ValueError:
        pass  # hostname is not an IP — that's fine

    # Allow *.svc.cluster.local and private RFC1918 for K8s internal comms
    # Block file:// and other exotic schemes (already handled by scheme check)

router = APIRouter(prefix="/api/config", tags=["config"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ConnectionConfig(BaseModel):
    od_url: str = ""


class ConnectionUpdateRequest(BaseModel):
    od_url: str = Field(..., description="Open Design daemon URL (e.g. http://open-design-svc:7457)")
    restart: bool = Field(default=True, description="Restart MCP server after update")


class ConnectionUpdateResponse(BaseModel):
    success: bool
    message: str
    restarted: bool = False


class ConnectionTestRequest(BaseModel):
    od_url: str


class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    version: str | None = None
    agent_count: int | None = None
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ConnectionConfig)
async def get_config() -> ConnectionConfig:
    """Return current connection config."""
    store = get_config_store()
    conn = await store.get("connection", {})
    return ConnectionConfig(
        od_url=conn.get("od_url", ""),
    )


@router.put("/connection", response_model=ConnectionUpdateResponse)
async def update_connection(req: ConnectionUpdateRequest) -> ConnectionUpdateResponse:
    """Update OD daemon URL and optionally restart MCP server."""
    store = get_config_store()
    await store.patch("connection", {"od_url": req.od_url})
    logger.info("Updated OD daemon URL to %s", req.od_url)

    restarted = False
    if req.restart:
        pm = get_process_manager()
        if pm.is_running:
            await pm.restart()
            restarted = True

    return ConnectionUpdateResponse(
        success=True,
        message="Connection settings updated",
        restarted=restarted,
    )


@router.post("/test", response_model=ConnectionTestResponse)
async def test_connection(req: ConnectionTestRequest) -> ConnectionTestResponse:
    """Test HTTP connectivity to OD daemon."""
    url = req.od_url.rstrip("/")

    # SSRF protection — reject dangerous URLs
    _validate_url_ssrf(url)

    # 1. Check /api/health
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{url}/api/health")
    except httpx.ConnectError:
        return ConnectionTestResponse(success=False, message=f"Cannot connect to {url}")
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message=f"Connection to {url} timed out")
    except Exception as exc:
        return ConnectionTestResponse(success=False, message=f"Error: {exc}")

    if resp.status_code != 200:
        return ConnectionTestResponse(
            success=False,
            message=f"/api/health returned HTTP {resp.status_code}",
        )

    health_data = resp.json()
    if not health_data.get("ok"):
        return ConnectionTestResponse(
            success=False,
            message="Daemon reports unhealthy",
            details=health_data,
        )

    # 2. Get version info
    version = health_data.get("version", "unknown")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            ver_resp = await client.get(f"{url}/api/version")
            if ver_resp.status_code == 200:
                ver_data = ver_resp.json().get("version", version)
                # /api/version may return {"version": {"version": "x.y.z", ...}}
                if isinstance(ver_data, dict):
                    version = ver_data.get("version", version)
                else:
                    version = str(ver_data)
    except Exception:
        pass

    # 3. Count agents
    agent_count = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            agents_resp = await client.get(f"{url}/api/agents")
            if agents_resp.status_code == 200:
                agents = agents_resp.json()
                if isinstance(agents, list):
                    agent_count = len(agents)
    except Exception:
        pass

    return ConnectionTestResponse(
        success=True,
        message=f"Connected to Open Design daemon v{version}",
        version=version,
        agent_count=agent_count,
        details={"url": url, "health": health_data},
    )
