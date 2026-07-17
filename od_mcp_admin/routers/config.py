"""Connection configuration router for Open Design MCP.

Manages OD daemon connection settings (simple HTTP URL).

Endpoints:
    GET  /api/config            - Current connection config
    PUT  /api/config/connection  - Update daemon URL
    POST /api/config/test        - Test HTTP connectivity to OD daemon
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from mcp_admin_core.config import get_config_store
from mcp_admin_core.process import get_process_manager

logger = logging.getLogger(__name__)

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
                version = ver_resp.json().get("version", version)
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
