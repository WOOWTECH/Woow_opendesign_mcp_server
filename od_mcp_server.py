#!/usr/bin/env python3
"""Open Design MCP Server — exposes OD daemon API as MCP tools.

Runs in stdio mode. Supergateway converts to StreamableHttp.
Connects to OD daemon at OD_API_BASE (default: http://open-design-svc:7457).
"""
import json
import os
import re
import time
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

# Pattern to extract project UUID from file paths like /app/.od/projects/{uuid}/file
_PROJECT_PATH_RE = re.compile(
    r"/\.od/projects/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)

OD_API_BASE = os.environ.get("OD_API_BASE", "http://open-design-svc:7457")

# Chat operations can take minutes (AI agent generates code)
CHAT_TIMEOUT = float(os.environ.get("OD_CHAT_TIMEOUT", "300"))

mcp = FastMCP("Open Design MCP Server")
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=OD_API_BASE, timeout=60.0)
    return _client


def _api_get(path: str) -> dict:
    """GET request to OD daemon API."""
    resp = _get_client().get(path)
    resp.raise_for_status()
    return resp.json()


def _api_post(path: str, data: dict | None = None) -> dict:
    """POST request to OD daemon API."""
    resp = _get_client().post(path, json=data or {})
    resp.raise_for_status()
    return resp.json()


def _get_project_ids() -> set[str]:
    """Get the set of current project IDs from the daemon."""
    try:
        data = _api_get("/api/projects")
        return {p["id"] for p in data.get("projects", [])}
    except Exception:
        return set()


def _api_post_sse(
    path: str,
    data: dict | None = None,
    project_ids_before: set[str] | None = None,
) -> dict:
    """POST request that consumes an SSE (event-stream) response.

    The OD daemon /api/chat returns Server-Sent Events. We stream through
    all events, collecting agent text output, and return a structured result
    once the stream ends.

    If project_ids_before is provided and the SSE stream returns projectId=null,
    we diff the project list to discover the newly created project.
    """
    client = httpx.Client(base_url=OD_API_BASE, timeout=httpx.Timeout(CHAT_TIMEOUT, connect=10.0))
    try:
        with client.stream("POST", path, json=data or {}) as resp:
            resp.raise_for_status()

            run_id = None
            project_id = None
            status = "unknown"
            agent_text = []
            errors = []
            discovered_project_ids = set()

            for line in resp.iter_lines():
                # SSE data lines: "data: {...}" or "data:{...}"
                if line.startswith("data:"):
                    json_str = line[5:].lstrip()
                    if not json_str:
                        continue
                    try:
                        payload = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

                    # Extract run metadata from "start" event
                    if "runId" in payload:
                        run_id = payload["runId"]
                        project_id = payload.get("projectId")

                    # Extract projectId from tool_use file paths
                    # Agent writes to /app/.od/projects/{uuid}/file
                    if payload.get("type") == "tool_use":
                        input_data = payload.get("input", {})
                        file_path = input_data.get("file_path", "")
                        m = _PROJECT_PATH_RE.search(file_path)
                        if m:
                            discovered_project_ids.add(m.group(1))

                    # Also check tool_result content for project paths
                    if payload.get("type") == "tool_result":
                        content = payload.get("content", "")
                        if isinstance(content, str):
                            for m in _PROJECT_PATH_RE.finditer(content):
                                discovered_project_ids.add(m.group(1))

                    # Collect agent text deltas
                    if payload.get("type") == "text_delta":
                        agent_text.append(payload.get("delta", ""))

                    # Capture errors
                    if "error" in payload and isinstance(payload["error"], dict):
                        errors.append(payload["error"].get("message", str(payload["error"])))

                    # Capture final status
                    if "status" in payload and "code" in payload:
                        status = payload["status"]

            # Resolve projectId if the SSE stream didn't report it.
            # Strategy 1: Use project ID extracted from agent's file writes.
            if not project_id and discovered_project_ids:
                project_id = discovered_project_ids.pop()

            # Strategy 2: Diff the project list to find newly created projects.
            if not project_id and project_ids_before is not None:
                for attempt in range(3):
                    current_ids = _get_project_ids()
                    new_ids = current_ids - project_ids_before
                    if new_ids:
                        project_id = new_ids.pop()
                        break
                    time.sleep(2)

            result = {
                "runId": run_id,
                "projectId": project_id,
                "status": status,
            }
            if agent_text:
                result["agentResponse"] = "".join(agent_text)
            if errors:
                result["errors"] = errors
                result["status"] = "failed"
            return result
    finally:
        client.close()


def _api_delete(path: str) -> dict:
    """DELETE request to OD daemon API."""
    resp = _get_client().delete(path)
    resp.raise_for_status()
    return resp.json()


# ═══════════════════════════════════════════════════════════════════
# Category A: System Tools (4)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def health() -> dict:
    """Check Open Design daemon health status and version."""
    return _api_get("/api/health")


@mcp.tool()
def version() -> dict:
    """Get detailed daemon version info (version, channel, platform, arch)."""
    return _api_get("/api/version")


@mcp.tool()
def list_agents() -> dict:
    """List all available AI agent CLIs (Claude Code, OpenCode, BYOK).

    Returns agent IDs, names, versions, availability status, and paths.
    """
    data = _api_get("/api/agents")
    # Filter to show only available agents for clarity
    available = [a for a in data.get("agents", []) if a.get("available")]
    return {
        "available_agents": available,
        "total_defined": len(data.get("agents", [])),
        "total_available": len(available),
    }


@mcp.tool()
def list_connectors() -> dict:
    """List available external connectors (GitHub, etc.) and their tools."""
    return _api_get("/api/connectors")


# ═══════════════════════════════════════════════════════════════════
# Category B: Project Tools (5)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def list_projects() -> dict:
    """List all design projects with their status, creation time, and metadata."""
    return _api_get("/api/projects")


@mcp.tool()
def get_project(project_id: str) -> dict:
    """Get detailed information about a specific project by ID.

    Args:
        project_id: UUID of the project (e.g. '38c010dc-f7c8-4a35-a325-89d6f56e45a4')
    """
    return _api_get(f"/api/projects/{project_id}")


@mcp.tool()
def create_project(prompt: str, agent_id: str = "claude") -> dict:
    """Create a new design project by sending an initial prompt to an AI agent.

    This is a long-running operation — the AI agent will generate code/design
    and the call blocks until completion (up to 5 minutes).

    Args:
        prompt: The initial design prompt (e.g. 'Create a landing page for a coffee shop')
        agent_id: Agent CLI to use ('claude', 'opencode', 'byok-opencode'). Default: 'claude'
    """
    # Snapshot project IDs before the call so we can discover the new project
    # (the daemon creates it during the run but never reports its ID via SSE).
    ids_before = _get_project_ids()
    return _api_post_sse("/api/chat", {
        "message": prompt,
        "agentId": agent_id,
    }, project_ids_before=ids_before)


@mcp.tool()
def delete_project(project_id: str) -> dict:
    """Permanently delete a project and all its files. This action cannot be undone.

    Args:
        project_id: UUID of the project to delete
    """
    return _api_delete(f"/api/projects/{project_id}")


@mcp.tool()
def list_project_files(project_id: str) -> dict:
    """List all files in a project directory with metadata (name, size, type, mime).

    Args:
        project_id: UUID of the project
    """
    return _api_get(f"/api/projects/{project_id}/files")


# ═══════════════════════════════════════════════════════════════════
# Category C: File Tools (2)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def read_file(project_id: str, file_path: str) -> str:
    """Read the raw content of a file from a project.

    Args:
        project_id: UUID of the project
        file_path: Relative path of the file within the project (e.g. 'index.html')
    """
    resp = _get_client().get(f"/api/projects/{project_id}/files/{file_path}")
    resp.raise_for_status()
    return resp.text


@mcp.tool()
def get_file_info(project_id: str, file_path: str) -> dict:
    """Get metadata about a specific file (size, mime type, artifact info).

    Args:
        project_id: UUID of the project
        file_path: Relative path of the file
    """
    data = _api_get(f"/api/projects/{project_id}/files")
    for f in data.get("files", []):
        if f.get("path") == file_path or f.get("name") == file_path:
            return f
    return {"error": f"File '{file_path}' not found in project"}


# ═══════════════════════════════════════════════════════════════════
# Category D: AI Chat Tools (2)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def send_message(
    project_id: str,
    prompt: str,
    agent_id: str = "claude",
) -> dict:
    """Send a follow-up message in an existing project's conversation.

    This is a long-running operation — the AI agent will process the message
    and the call blocks until completion (up to 5 minutes).

    Args:
        project_id: UUID of the project to continue
        prompt: The message to send to the AI agent
        agent_id: Agent CLI to use. Default: 'claude'
    """
    result = _api_post_sse("/api/chat", {
        "message": prompt,
        "agentId": agent_id,
        "projectId": project_id,
    })
    # Ensure projectId is always set for send_message (caller already knows it)
    if not result.get("projectId"):
        result["projectId"] = project_id
    return result


@mcp.tool()
def list_runs() -> dict:
    """List all active and completed AI agent runs."""
    return _api_get("/api/runs")


# ═══════════════════════════════════════════════════════════════════
# Category E: Content Tools (2)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def list_plugins() -> dict:
    """List all available plugins and templates (video, design, etc.)."""
    data = _api_get("/api/plugins")
    # Return summary instead of full plugin data (can be very large)
    plugins = data.get("plugins", [])
    return {
        "total": len(plugins),
        "plugins": [
            {
                "id": p["id"],
                "title": p.get("title", p["id"]),
                "source": p.get("sourceKind", "unknown"),
                "trust": p.get("trust", "unknown"),
            }
            for p in plugins
        ],
    }


@mcp.tool()
def list_skills() -> dict:
    """List all available design skills and their triggers."""
    data = _api_get("/api/skills")
    skills = data.get("skills", [])
    return {
        "total": len(skills),
        "skills": [
            {
                "id": s["id"],
                "name": s.get("name", s["id"]),
                "description": s.get("description", ""),
                "mode": s.get("mode", ""),
                "surface": s.get("surface", ""),
                "triggers": s.get("triggers", [])[:5],
            }
            for s in skills
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
