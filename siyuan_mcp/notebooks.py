"""Notebook discovery, creation, and connection checks."""

from __future__ import annotations

from typing import Any

from siyuan_mcp import core
from siyuan_mcp.core import mcp


@mcp.tool()
def siyuan_ping() -> dict[str, Any]:
    """Check whether the SiYuan kernel is reachable and the token works."""
    version = core.call_siyuan("/api/system/version", {})
    notebooks = core.call_siyuan("/api/notebook/lsNotebooks", {})
    return {
        "ok": True,
        "baseUrl": core.current_base_url(),
        "version": version,
        "notebooks": [public_notebook(item) for item in core.extract_notebooks(notebooks)],
    }

@mcp.tool()
def siyuan_list_notebooks() -> dict[str, Any]:
    """List SiYuan notebooks."""
    data = core.call_siyuan("/api/notebook/lsNotebooks", {})
    return {"notebooks": [public_notebook(item) for item in core.extract_notebooks(data)]}

@mcp.tool()
def siyuan_ensure_notebook(name: str, create: bool = True) -> dict[str, Any]:
    """Find a notebook by id or name, or create it when it does not exist."""
    existing = core.find_notebook(name)
    if existing:
        return {"created": False, "notebook": public_notebook(existing)}

    if not create:
        return {"created": False, "notebook": None}

    created = core.call_siyuan("/api/notebook/createNotebook", {"name": name})
    notebook_key = (
        core.dig(created, "notebook", "id")
        or core.dig(created, "box")
        or name
    )
    notebook = core.find_notebook(str(notebook_key))
    return {
        "created": True,
        "raw": created,
        "notebook": public_notebook(notebook) if notebook else None,
    }

def public_notebook(notebook: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": notebook.get("id") or notebook.get("box") or notebook.get("notebook"),
        "name": notebook.get("name"),
        "closed": bool(notebook.get("closed")),
    }
