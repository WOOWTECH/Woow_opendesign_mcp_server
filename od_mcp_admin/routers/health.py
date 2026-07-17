"""Health dashboard router for Open Design MCP.

Checks OD daemon health via HTTP and MCP server process status.

Endpoints:
    GET /api/health - Dashboard health data
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter

from mcp_admin_core.config import get_config_store
from mcp_admin_core.process import get_process_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


async def _check_od_daemon(od_url: str) -> dict[str, Any]:
    """Check Open Design daemon health via /api/health."""
    if not od_url:
        return {"healthy": False, "url": "", "error": "Not configured"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{od_url.rstrip('/')}/api/health")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "healthy": data.get("ok", False),
                    "url": od_url,
                    "version": data.get("version", "unknown"),
                }
            return {"healthy": False, "url": od_url, "status_code": resp.status_code}
    except httpx.ConnectError:
        return {"healthy": False, "url": od_url, "error": "Connection refused"}
    except httpx.TimeoutException:
        return {"healthy": False, "url": od_url, "error": "Timed out"}
    except Exception as exc:
        return {"healthy": False, "url": od_url, "error": str(exc)}


async def _get_od_info(od_url: str) -> dict[str, Any]:
    """Get Open Design version and agent count."""
    info: dict[str, Any] = {"version": None, "agent_count": None}
    if not od_url:
        return info
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get version
            resp = await client.get(f"{od_url.rstrip('/')}/api/version")
            if resp.status_code == 200:
                data = resp.json()
                info["version"] = data.get("version", "unknown")

            # Get agent count
            resp = await client.get(f"{od_url.rstrip('/')}/api/agents")
            if resp.status_code == 200:
                agents = resp.json()
                if isinstance(agents, list):
                    info["agent_count"] = len(agents)
    except Exception as exc:
        logger.debug("Failed to get OD info: %s", exc)
    return info


async def _check_mcp_health(mcp_port: int) -> dict[str, Any]:
    """Check supergateway /healthz endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://127.0.0.1:{mcp_port}/healthz")
            return {"healthy": resp.status_code == 200}
    except Exception:
        return {"healthy": False}


@router.get("")
async def get_health() -> dict[str, Any]:
    """Return health data for the Dashboard frontend."""
    store = get_config_store()
    pm = get_process_manager()

    conn = await store.get("connection", {})
    od_url = conn.get("od_url", "") or os.environ.get("OD_API_BASE", "")
    mcp_cfg = await store.get("mcp_server", {})
    mcp_port = mcp_cfg.get("port", int(os.environ.get("MCP_SERVER_PORT", "8000")))

    pm_status = await pm.status()

    # Check MCP supergateway health (started by entrypoint, not process manager)
    mcp_health = await _check_mcp_health(mcp_port)
    mcp_running = pm_status.get("running", False)
    sg_healthy = mcp_health.get("healthy", False)
    mcp_server = {
        "healthy": mcp_running or sg_healthy,
        "pod_name": f"pid={pm_status.get('pid')}" if mcp_running else ("supergateway" if sg_healthy else "stopped"),
        "restart_count": pm_status.get("restart_count", 0),
    }

    # Check OD daemon
    target_app = await _check_od_daemon(od_url)
    proxy = {"healthy": True, "pod_name": "built-in reverse proxy"}

    # Get OD info (version, agent count)
    od_info = await _get_od_info(od_url)

    all_healthy = mcp_server["healthy"] and target_app.get("healthy", False)

    return {
        "app_type": "open-design",
        "overall_status": "ok" if all_healthy else "degraded" if mcp_running or target_app.get("healthy") else "error",
        "mcp_server": mcp_server,
        "target_app": target_app,
        "proxy": proxy,
        "version": od_info.get("version"),
        "agent_count": od_info.get("agent_count"),
        "namespace": "open-design",
    }
