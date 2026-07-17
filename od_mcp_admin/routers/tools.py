"""Tool management router for Open Design MCP.

Manages the enable/disable state of all OD MCP tools.
Tool states are persisted in the file-backed config store under
the ``tools`` key.

Endpoints:
    GET /api/tools - List all tools with categories and enabled status
    PUT /api/tools - Update tool enable/disable states
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from mcp_admin_core.config import get_config_store

from ..tool_registry import (
    TOOL_BY_NAME,
    TOOL_REGISTRY,
    ToolCategory,
    ToolState,
    ToolUpdateRequest,
    ToolUpdateResponse,
    get_category_summary,
    get_tool_states,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ToolListResponse(BaseModel):
    """Response for the tool listing endpoint."""

    total: int
    categories: dict[str, dict[str, Any]]
    tools: list[ToolState]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_tool_overrides() -> dict[str, bool]:
    """Load tool enabled/disabled overrides from the config store."""
    try:
        store = get_config_store()
        tools_cfg = await store.get("tools", {})
        if isinstance(tools_cfg, dict):
            if "disabled" in tools_cfg:
                overrides: dict[str, bool] = {}
                for name in tools_cfg.get("disabled", []):
                    overrides[name] = False
                for key, val in tools_cfg.items():
                    if key not in ("disabled", "disabled_operations") and isinstance(val, bool):
                        overrides[key] = val
                return overrides
            return {k: v for k, v in tools_cfg.items() if isinstance(v, bool)}
        return {}
    except Exception as exc:
        logger.warning("Could not read tools config, using defaults: %s", exc)
        return {}


async def _save_tool_overrides(overrides: dict[str, bool]) -> None:
    """Persist tool enabled/disabled overrides to the config store."""
    store = get_config_store()
    disabled_list = [name for name, enabled in overrides.items() if not enabled]
    await store.put("tools", {
        "disabled": disabled_list,
        "disabled_operations": {},
        **overrides,
    })


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """Return all OD MCP tools with categories and current enabled status."""
    try:
        overrides = await _load_tool_overrides()
        tool_states = get_tool_states(overrides)
        categories = get_category_summary()

        return ToolListResponse(
            total=len(TOOL_REGISTRY),
            categories=categories,
            tools=tool_states,
        )
    except Exception as exc:
        logger.error("Failed to list tools: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tools: {exc}",
        ) from exc


@router.put("", response_model=ToolUpdateResponse)
async def update_tools(req: ToolUpdateRequest) -> ToolUpdateResponse:
    """Update tool enable/disable states."""
    if isinstance(req.tools, dict):
        raw_updates: dict[str, bool] = {
            k: v for k, v in req.tools.items() if isinstance(v, bool)
        }
    elif isinstance(req.tools, list):
        raw_updates = {
            t["name"]: t.get("enabled", True)
            for t in req.tools
            if isinstance(t, dict) and "name" in t
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'tools' must be a dict or list",
        )

    unknown_tools = [name for name in raw_updates if name not in TOOL_BY_NAME]
    if unknown_tools:
        logger.warning("Ignoring unknown tool names: %s", unknown_tools)

    valid_updates = {
        name: enabled
        for name, enabled in raw_updates.items()
        if name in TOOL_BY_NAME
    }

    if not valid_updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid tool names provided",
        )

    try:
        current_overrides = await _load_tool_overrides()
        current_overrides.update(valid_updates)
        await _save_tool_overrides(current_overrides)

        tool_states = get_tool_states(current_overrides)

        return ToolUpdateResponse(
            updated=len(valid_updates),
            tools=tool_states,
        )
    except Exception as exc:
        logger.error("Failed to update tools: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update tools: {exc}",
        ) from exc
