"""Document creation, lookup, movement, removal, and export."""

from __future__ import annotations

from typing import Any

from siyuan_mcp import core
from siyuan_mcp.core import mcp


@mcp.tool()
def siyuan_create_doc(
    path: str,
    markdown: str = "",
    notebook: str | None = None,
) -> dict[str, Any]:
    """Create a document from Markdown under a notebook path."""
    notebook_id = core.resolve_notebook_id(notebook)
    doc_path = core.normalize_doc_path(path)
    data = core.call_siyuan(
        "/api/filetree/createDocWithMd",
        {
            "notebook": notebook_id,
            "path": doc_path,
            "markdown": markdown,
        },
    )
    return {
        "notebook": notebook_id,
        "path": doc_path,
        "id": extract_created_id(data),
        "raw": data,
    }

@mcp.tool()
def siyuan_ensure_doc(
    path: str,
    markdown: str = "",
    notebook: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Find or create a document by notebook path."""
    notebook_id = core.resolve_notebook_id(notebook)
    doc_path = core.normalize_doc_path(path)
    existing_id = core.get_doc_id_by_path(notebook_id, doc_path)

    doc_id = existing_id
    created = False
    raw = None

    if not doc_id:
        raw = core.call_siyuan(
            "/api/filetree/createDocWithMd",
            {
                "notebook": notebook_id,
                "path": doc_path,
                "markdown": markdown,
            },
        )
        doc_id = extract_created_id(raw) or core.get_doc_id_by_path(notebook_id, doc_path)
        created = True

    if doc_id and attrs:
        core.call_siyuan("/api/attr/setBlockAttrs", {"id": doc_id, "attrs": attrs})

    return {
        "created": created,
        "notebook": notebook_id,
        "path": doc_path,
        "id": doc_id,
        "raw": raw,
    }

@mcp.tool()
def siyuan_get_doc_id_by_path(path: str, notebook: str | None = None) -> dict[str, Any]:
    """Resolve a document id from a notebook path."""
    notebook_id = core.resolve_notebook_id(notebook)
    doc_path = core.normalize_doc_path(path)
    return {
        "notebook": notebook_id,
        "path": doc_path,
        "id": core.get_doc_id_by_path(notebook_id, doc_path),
    }

@mcp.tool()
def siyuan_get_doc_paths_by_id(id: str) -> dict[str, Any]:
    """Resolve both human-readable and storage paths for a document id."""
    hpath = core.call_siyuan("/api/filetree/getHPathByID", {"id": id})
    storage = core.call_siyuan("/api/filetree/getPathByID", {"id": id})
    return {"id": id, "hpath": hpath, "storage": storage}

@mcp.tool()
def siyuan_remove_doc_by_id(id: str, verify: bool = True) -> dict[str, Any]:
    """Remove a document by id using SiYuan's filetree API, then flush and optionally verify."""
    result = core.call_siyuan("/api/filetree/removeDocByID", {"id": id})
    flush_transaction()
    remaining = find_doc_row_by_id(id) if verify else None

    fallback = None
    if verify and remaining:
        storage_path = remaining.get("path")
        notebook = remaining.get("box")
        if storage_path and notebook:
            fallback = core.call_siyuan(
                "/api/filetree/removeDoc",
                {"notebook": notebook, "path": storage_path},
            )
            flush_transaction()
            remaining = find_doc_row_by_id(id)

    return {
        "id": id,
        "removed": remaining is None if verify else True,
        "remaining": remaining,
        "fallback": fallback,
        "raw": result,
    }

@mcp.tool()
def siyuan_remove_doc_by_path(
    path: str,
    notebook: str | None = None,
    verify: bool = True,
) -> dict[str, Any]:
    """Remove a document by human-readable path. The path is resolved to an id first."""
    notebook_id = core.resolve_notebook_id(notebook)
    doc_path = core.normalize_doc_path(path)
    doc_id = core.get_doc_id_by_path(notebook_id, doc_path)

    if not doc_id:
        raw = core.call_siyuan("/api/filetree/removeDoc", {"notebook": notebook_id, "path": doc_path})
        flush_transaction()
        remaining = core.get_doc_id_by_path(notebook_id, doc_path) if verify else None
        return {
            "notebook": notebook_id,
            "path": doc_path,
            "id": None,
            "removed": remaining is None if verify else True,
            "remaining": remaining,
            "raw": raw,
        }

    removed = siyuan_remove_doc_by_id(doc_id, verify=verify)
    return {"notebook": notebook_id, "path": doc_path, **removed}

@mcp.tool()
def siyuan_rename_doc_by_id(id: str, title: str) -> dict[str, Any]:
    """Rename a document by id."""
    if not title.strip():
        raise ValueError("title cannot be empty.")
    result = core.call_siyuan("/api/filetree/renameDocByID", {"id": id, "title": title.strip()})
    flush_transaction()
    return {"id": id, "title": title.strip(), "hpath": core.get_hpath_by_id(id), "raw": result}

@mcp.tool()
def siyuan_rename_doc_by_path(
    path: str,
    title: str,
    notebook: str | None = None,
) -> dict[str, Any]:
    """Rename a document by human-readable path. The path is resolved to an id first."""
    notebook_id = core.resolve_notebook_id(notebook)
    doc_path = core.normalize_doc_path(path)
    doc_id = core.get_doc_id_by_path(notebook_id, doc_path)
    if not doc_id:
        raise ValueError(f"Document not found: {doc_path}")
    renamed = siyuan_rename_doc_by_id(doc_id, title)
    return {"notebook": notebook_id, "oldPath": doc_path, **renamed}

@mcp.tool()
def siyuan_move_docs_by_id(fromIds: list[str], toId: str) -> dict[str, Any]:
    """Move documents by id to a target parent document id or notebook id."""
    if not fromIds:
        raise ValueError("fromIds cannot be empty.")
    result = core.call_siyuan("/api/filetree/moveDocsByID", {"fromIDs": fromIds, "toID": toId})
    flush_transaction()
    return {"fromIds": fromIds, "toId": toId, "raw": result}

@mcp.tool()
def siyuan_move_doc_by_path(
    path: str,
    toParentPath: str = "/",
    notebook: str | None = None,
    toNotebook: str | None = None,
) -> dict[str, Any]:
    """Move one document by human-readable path to another parent path or notebook root."""
    from_notebook = core.resolve_notebook_id(notebook)
    target_notebook = core.resolve_notebook_id(toNotebook or from_notebook)
    doc_path = core.normalize_doc_path(path)
    parent_path = core.normalize_doc_path(toParentPath)
    doc_id = core.get_doc_id_by_path(from_notebook, doc_path)
    if not doc_id:
        raise ValueError(f"Document not found: {doc_path}")

    to_id = target_notebook if parent_path == "/" else core.get_doc_id_by_path(target_notebook, parent_path)
    if not to_id:
        raise ValueError(f"Target parent not found: {parent_path}")

    moved = siyuan_move_docs_by_id([doc_id], to_id)
    return {
        "fromNotebook": from_notebook,
        "toNotebook": target_notebook,
        "path": doc_path,
        "toParentPath": parent_path,
        **moved,
    }

@mcp.tool()
def siyuan_upsert_doc_section(
    path: str,
    markdown: str,
    title: str | None = None,
    notebook: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a document if needed, then append a section to it."""
    notebook_id = core.resolve_notebook_id(notebook)
    doc_path = core.normalize_doc_path(path)
    existing_id = core.get_doc_id_by_path(notebook_id, doc_path)
    initial_markdown = f"## {title}\n\n{markdown}\n" if title else markdown

    doc_id = existing_id
    created = False
    if not doc_id:
        raw = core.call_siyuan(
            "/api/filetree/createDocWithMd",
            {
                "notebook": notebook_id,
                "path": doc_path,
                "markdown": initial_markdown,
            },
        )
        doc_id = extract_created_id(raw) or core.get_doc_id_by_path(notebook_id, doc_path)
        created = True
    else:
        section = f"\n\n## {title}\n\n{markdown}\n" if title else f"\n\n{markdown}\n"
        core.call_siyuan(
            "/api/block/appendBlock",
            {
                "parentID": doc_id,
                "dataType": "markdown",
                "data": section,
            },
        )

    if doc_id and attrs:
        core.call_siyuan("/api/attr/setBlockAttrs", {"id": doc_id, "attrs": attrs})

    return {"created": created, "notebook": notebook_id, "path": doc_path, "id": doc_id}

@mcp.tool()
def siyuan_export_doc_markdown(id: str) -> dict[str, Any]:
    """Export a document as Markdown if the SiYuan kernel supports the export endpoint."""
    data = core.call_siyuan("/api/export/exportMdContent", {"id": id})
    markdown = data
    if isinstance(data, dict):
        markdown = data.get("content") or data.get("markdown") or data
    return {"id": id, "markdown": markdown, "raw": data}

def find_doc_row_by_id(id: str) -> dict[str, Any] | None:
    rows = core.call_siyuan(
        "/api/query/sql",
        {"stmt": "SELECT id, box, path, hpath, content FROM blocks WHERE type = 'd' AND id = " + core.sql_string(id)},
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None

def flush_transaction() -> None:
    core.call_siyuan("/api/sqlite/flushTransaction", {})

def extract_created_id(data: Any) -> str | None:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return None
    return (
        data.get("id")
        or data.get("docID")
        or data.get("blockID")
        or core.dig(data, "block", "id")
    )
