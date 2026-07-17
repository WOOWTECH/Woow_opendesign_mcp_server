"""Registry of all Open Design MCP tools organized by category.

Each tool maps to an endpoint on the OD daemon API at /api/*.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ToolCategory(str, Enum):
    SYSTEM = "A - System"
    PROJECT = "B - Project"
    FILE = "C - File"
    CHAT = "D - AI Chat"
    CONTENT = "E - Content"


class ToolDefinition(BaseModel):
    name: str
    description: str
    category: ToolCategory
    enabled_by_default: bool = True
    dangerous: bool = False


class ToolState(BaseModel):
    name: str
    description: str
    category: ToolCategory
    enabled_by_default: bool
    dangerous: bool
    enabled: bool


class ToolUpdateRequest(BaseModel):
    tools: Any  # dict[str, bool] from frontend


class ToolUpdateResponse(BaseModel):
    updated: int
    tools: list[ToolState]


# ---------------------------------------------------------------------------
# Complete registry of Open Design MCP tools (15 tools, 5 categories)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: list[ToolDefinition] = [
    # ── A - System (4) ─────────────────────────────────────────────
    ToolDefinition(
        name="health",
        description="Check OD daemon health status and version",
        category=ToolCategory.SYSTEM,
    ),
    ToolDefinition(
        name="version",
        description="Get detailed daemon version info",
        category=ToolCategory.SYSTEM,
    ),
    ToolDefinition(
        name="list_agents",
        description="List available AI agent CLIs (Claude Code, OpenCode, BYOK)",
        category=ToolCategory.SYSTEM,
    ),
    ToolDefinition(
        name="list_connectors",
        description="List external connectors (GitHub, etc.) and their tools",
        category=ToolCategory.SYSTEM,
    ),
    # ── B - Project (5) ───────────────────────────────────────────
    ToolDefinition(
        name="list_projects",
        description="List all design projects with status and metadata",
        category=ToolCategory.PROJECT,
    ),
    ToolDefinition(
        name="get_project",
        description="Get project details by ID",
        category=ToolCategory.PROJECT,
    ),
    ToolDefinition(
        name="create_project",
        description="Create a new design project with an AI agent",
        category=ToolCategory.PROJECT,
    ),
    ToolDefinition(
        name="delete_project",
        description="Permanently delete a project and all its files",
        category=ToolCategory.PROJECT,
        dangerous=True,
    ),
    ToolDefinition(
        name="list_project_files",
        description="List files in a project directory",
        category=ToolCategory.PROJECT,
    ),
    # ── C - File (2) ──────────────────────────────────────────────
    ToolDefinition(
        name="read_file",
        description="Read raw file content from a project",
        category=ToolCategory.FILE,
    ),
    ToolDefinition(
        name="get_file_info",
        description="Get file metadata (size, mime type, artifact info)",
        category=ToolCategory.FILE,
    ),
    # ── D - AI Chat (2) ──────────────────────────────────────────
    ToolDefinition(
        name="send_message",
        description="Send a message to an AI agent in an existing project",
        category=ToolCategory.CHAT,
    ),
    ToolDefinition(
        name="list_runs",
        description="List active and completed AI agent runs",
        category=ToolCategory.CHAT,
    ),
    # ── E - Content (2) ──────────────────────────────────────────
    ToolDefinition(
        name="list_plugins",
        description="List available plugins and templates",
        category=ToolCategory.CONTENT,
    ),
    ToolDefinition(
        name="list_skills",
        description="List available design skills and triggers",
        category=ToolCategory.CONTENT,
    ),
]

# Pre-built lookups
TOOL_BY_NAME: dict[str, ToolDefinition] = {t.name: t for t in TOOL_REGISTRY}

TOOLS_BY_CATEGORY: dict[ToolCategory, list[ToolDefinition]] = {}
for _tool in TOOL_REGISTRY:
    TOOLS_BY_CATEGORY.setdefault(_tool.category, []).append(_tool)


def get_tool_states(enabled_overrides: dict[str, bool] | None = None) -> list[ToolState]:
    """Build tool state list with optional enabled overrides."""
    overrides = enabled_overrides or {}
    return [
        ToolState(
            name=t.name,
            description=t.description,
            category=t.category,
            enabled_by_default=t.enabled_by_default,
            dangerous=t.dangerous,
            enabled=overrides.get(t.name, t.enabled_by_default),
        )
        for t in TOOL_REGISTRY
    ]


def get_category_summary() -> dict[str, dict[str, Any]]:
    """Return summary of tools per category."""
    return {
        cat.value: {
            "count": len(tools),
            "tools": [t.name for t in tools],
        }
        for cat, tools in TOOLS_BY_CATEGORY.items()
    }
