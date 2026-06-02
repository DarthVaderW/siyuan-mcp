"""SiYuan MCP server: documents, blocks, search, attributes, and AttributeView.

Shared infrastructure (the FastMCP instance, runtime config, and the SiYuan
HTTP client) lives in :mod:`siyuan_mcp.core`. AttributeView/database
tools live in :mod:`siyuan_mcp.attributeview`. This module defines the
document/block/search tools, the runtime entry point, and registers the other
tool modules.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from siyuan_mcp.core import (
    VERSION,
    assert_api_endpoint,
    call_siyuan,
    current_allow_raw_api,
    current_base_url,
    current_default_notebook,
    current_token,
    extract_notebooks,
    find_notebook,
    get_doc_id_by_path,
    get_hpath_by_id,
    mcp,
    normalize_doc_path,
    resolve_notebook_id,
    stable_json,
)


@mcp.resource("siyuan://config")
def siyuan_config() -> str:
    """Runtime configuration without secrets."""
    token = current_token()
    return stable_json(
        {
            "name": "siyuan-mcp",
            "version": VERSION,
            "baseUrl": current_base_url(),
            "defaultNotebook": current_default_notebook() or None,
            "tokenConfigured": bool(token),
            "rawApiEnabled": current_allow_raw_api(),
            "implementation": "python",
        }
    )


@mcp.tool()
def siyuan_ping() -> dict[str, Any]:
    """Check whether the SiYuan kernel is reachable and the token works."""
    version = call_siyuan("/api/system/version", {})
    notebooks = call_siyuan("/api/notebook/lsNotebooks", {})
    return {
        "ok": True,
        "baseUrl": current_base_url(),
        "version": version,
        "notebooks": [public_notebook(item) for item in extract_notebooks(notebooks)],
    }


@mcp.tool()
def siyuan_list_notebooks() -> dict[str, Any]:
    """List SiYuan notebooks."""
    data = call_siyuan("/api/notebook/lsNotebooks", {})
    return {"notebooks": [public_notebook(item) for item in extract_notebooks(data)]}


@mcp.tool()
def siyuan_ensure_notebook(name: str, create: bool = True) -> dict[str, Any]:
    """Find a notebook by id or name, or create it when it does not exist."""
    existing = find_notebook(name)
    if existing:
        return {"created": False, "notebook": public_notebook(existing)}

    if not create:
        return {"created": False, "notebook": None}

    created = call_siyuan("/api/notebook/createNotebook", {"name": name})
    notebook_key = (
        dig(created, "notebook", "id")
        or dig(created, "box")
        or name
    )
    notebook = find_notebook(str(notebook_key))
    return {
        "created": True,
        "raw": created,
        "notebook": public_notebook(notebook) if notebook else None,
    }


@mcp.tool()
def siyuan_create_doc(
    path: str,
    markdown: str = "",
    notebook: str | None = None,
) -> dict[str, Any]:
    """Create a document from Markdown under a notebook path."""
    notebook_id = resolve_notebook_id(notebook)
    doc_path = normalize_doc_path(path)
    data = call_siyuan(
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
    notebook_id = resolve_notebook_id(notebook)
    doc_path = normalize_doc_path(path)
    existing_id = get_doc_id_by_path(notebook_id, doc_path)

    doc_id = existing_id
    created = False
    raw = None

    if not doc_id:
        raw = call_siyuan(
            "/api/filetree/createDocWithMd",
            {
                "notebook": notebook_id,
                "path": doc_path,
                "markdown": markdown,
            },
        )
        doc_id = extract_created_id(raw) or get_doc_id_by_path(notebook_id, doc_path)
        created = True

    if doc_id and attrs:
        call_siyuan("/api/attr/setBlockAttrs", {"id": doc_id, "attrs": attrs})

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
    notebook_id = resolve_notebook_id(notebook)
    doc_path = normalize_doc_path(path)
    return {
        "notebook": notebook_id,
        "path": doc_path,
        "id": get_doc_id_by_path(notebook_id, doc_path),
    }


@mcp.tool()
def siyuan_get_doc_paths_by_id(id: str) -> dict[str, Any]:
    """Resolve both human-readable and storage paths for a document id."""
    hpath = call_siyuan("/api/filetree/getHPathByID", {"id": id})
    storage = call_siyuan("/api/filetree/getPathByID", {"id": id})
    return {"id": id, "hpath": hpath, "storage": storage}


@mcp.tool()
def siyuan_remove_doc_by_id(id: str, verify: bool = True) -> dict[str, Any]:
    """Remove a document by id using SiYuan's filetree API, then flush and optionally verify."""
    result = call_siyuan("/api/filetree/removeDocByID", {"id": id})
    flush_transaction()
    remaining = find_doc_row_by_id(id) if verify else None

    fallback = None
    if verify and remaining:
        storage_path = remaining.get("path")
        notebook = remaining.get("box")
        if storage_path and notebook:
            fallback = call_siyuan(
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
    notebook_id = resolve_notebook_id(notebook)
    doc_path = normalize_doc_path(path)
    doc_id = get_doc_id_by_path(notebook_id, doc_path)

    if not doc_id:
        raw = call_siyuan("/api/filetree/removeDoc", {"notebook": notebook_id, "path": doc_path})
        flush_transaction()
        remaining = get_doc_id_by_path(notebook_id, doc_path) if verify else None
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
    result = call_siyuan("/api/filetree/renameDocByID", {"id": id, "title": title.strip()})
    flush_transaction()
    return {"id": id, "title": title.strip(), "hpath": get_hpath_by_id(id), "raw": result}


@mcp.tool()
def siyuan_rename_doc_by_path(
    path: str,
    title: str,
    notebook: str | None = None,
) -> dict[str, Any]:
    """Rename a document by human-readable path. The path is resolved to an id first."""
    notebook_id = resolve_notebook_id(notebook)
    doc_path = normalize_doc_path(path)
    doc_id = get_doc_id_by_path(notebook_id, doc_path)
    if not doc_id:
        raise ValueError(f"Document not found: {doc_path}")
    renamed = siyuan_rename_doc_by_id(doc_id, title)
    return {"notebook": notebook_id, "oldPath": doc_path, **renamed}


@mcp.tool()
def siyuan_move_docs_by_id(fromIds: list[str], toId: str) -> dict[str, Any]:
    """Move documents by id to a target parent document id or notebook id."""
    if not fromIds:
        raise ValueError("fromIds cannot be empty.")
    result = call_siyuan("/api/filetree/moveDocsByID", {"fromIDs": fromIds, "toID": toId})
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
    from_notebook = resolve_notebook_id(notebook)
    target_notebook = resolve_notebook_id(toNotebook or from_notebook)
    doc_path = normalize_doc_path(path)
    parent_path = normalize_doc_path(toParentPath)
    doc_id = get_doc_id_by_path(from_notebook, doc_path)
    if not doc_id:
        raise ValueError(f"Document not found: {doc_path}")

    to_id = target_notebook if parent_path == "/" else get_doc_id_by_path(target_notebook, parent_path)
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
def siyuan_find_docs_by_attrs(
    attrs: dict[str, Any],
    notebook: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find document blocks whose IAL contains all provided attributes."""
    if not attrs:
        raise ValueError("attrs cannot be empty.")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")

    filters = ["type = 'd'"]
    if notebook:
        filters.append("box = " + sql_string(resolve_notebook_id(notebook)))

    for key, value in attrs.items():
        assert_attr_key(key)
        if value is None:
            filters.append("ial LIKE " + sql_string(f"%{key}=%"))
        else:
            filters.append("ial LIKE " + sql_string(f"%{key}=\"{str(value)}\"%"))

    stmt = " ".join(
        [
            "SELECT id, box, path, hpath, content, ial, updated",
            "FROM blocks",
            "WHERE " + " AND ".join(filters),
            "ORDER BY updated DESC",
            "LIMIT " + str(int(limit)),
        ]
    )
    rows = call_siyuan("/api/query/sql", {"stmt": stmt})
    return {"rows": rows, "stmt": stmt}


@mcp.tool()
def siyuan_get_block_markdown(id: str) -> dict[str, Any]:
    """Read a block or document as Kramdown/Markdown."""
    data = call_siyuan("/api/block/getBlockKramdown", {"id": id})
    return {"id": id, "markdown": data.get("kramdown") if isinstance(data, dict) else data, "raw": data}


@mcp.tool()
def siyuan_insert_block(
    parentId: str,
    data: str,
    dataType: Literal["markdown", "dom"] = "markdown",
    position: Literal["append", "prepend"] = "append",
) -> dict[str, Any]:
    """Append or prepend a Markdown/DOM block under a parent block."""
    endpoint = "/api/block/prependBlock" if position == "prepend" else "/api/block/appendBlock"
    result = call_siyuan(
        endpoint,
        {
            "parentID": parentId,
            "data": data,
            "dataType": dataType,
        },
    )
    return {
        "parentId": parentId,
        "position": position,
        "inserted": extract_block_ids(result),
        "raw": result,
    }


@mcp.tool()
def siyuan_update_block(
    id: str,
    data: str,
    dataType: Literal["markdown", "dom"] = "markdown",
) -> dict[str, Any]:
    """Replace a block's content with Markdown or DOM."""
    result = call_siyuan("/api/block/updateBlock", {"id": id, "data": data, "dataType": dataType})
    return {"id": id, "updated": True, "raw": result}


@mcp.tool()
def siyuan_delete_block(id: str) -> dict[str, Any]:
    """Delete a block by id."""
    result = call_siyuan("/api/block/deleteBlock", {"id": id})
    return {"id": id, "deleted": True, "raw": result}


@mcp.tool()
def siyuan_get_block_attrs(id: str) -> dict[str, Any]:
    """Read custom attributes from a block."""
    attrs = call_siyuan("/api/attr/getBlockAttrs", {"id": id})
    return {"id": id, "attrs": attrs}


@mcp.tool()
def siyuan_set_block_attrs(id: str, attrs: dict[str, Any]) -> dict[str, Any]:
    """Set custom attributes on a block."""
    result = call_siyuan("/api/attr/setBlockAttrs", {"id": id, "attrs": attrs})
    return {"id": id, "attrs": attrs, "raw": result}


@mcp.tool()
def siyuan_sql_query(stmt: str, limit: int = 100) -> dict[str, Any]:
    """Run a read-only SQL query against SiYuan's block database."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    assert_read_only_sql(stmt)
    data = call_siyuan("/api/query/sql", {"stmt": stmt})
    if isinstance(data, list):
        return {"rows": data[:limit], "truncated": len(data) > limit}
    return {"rows": data, "truncated": False}


@mcp.tool()
def siyuan_search_blocks(
    keyword: str,
    notebook: str | None = None,
    type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search blocks by text using SiYuan SQL."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    filters = [f"content LIKE {sql_string('%' + keyword + '%')}"]
    if notebook:
        filters.append(f"box = {sql_string(resolve_notebook_id(notebook))}")
    if type:
        filters.append(f"type = {sql_string(type)}")

    stmt = " ".join(
        [
            "SELECT id, box, path, hpath, name, alias, memo, tag, type, subtype, content, updated",
            "FROM blocks",
            "WHERE " + " AND ".join(filters),
            "ORDER BY updated DESC",
            "LIMIT " + str(int(limit)),
        ]
    )
    rows = call_siyuan("/api/query/sql", {"stmt": stmt})
    return {"rows": rows}


@mcp.tool()
def siyuan_upsert_doc_section(
    path: str,
    markdown: str,
    title: str | None = None,
    notebook: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a document if needed, then append a section to it."""
    notebook_id = resolve_notebook_id(notebook)
    doc_path = normalize_doc_path(path)
    existing_id = get_doc_id_by_path(notebook_id, doc_path)
    initial_markdown = f"## {title}\n\n{markdown}\n" if title else markdown

    doc_id = existing_id
    created = False
    if not doc_id:
        raw = call_siyuan(
            "/api/filetree/createDocWithMd",
            {
                "notebook": notebook_id,
                "path": doc_path,
                "markdown": initial_markdown,
            },
        )
        doc_id = extract_created_id(raw) or get_doc_id_by_path(notebook_id, doc_path)
        created = True
    else:
        section = f"\n\n## {title}\n\n{markdown}\n" if title else f"\n\n{markdown}\n"
        call_siyuan(
            "/api/block/appendBlock",
            {
                "parentID": doc_id,
                "dataType": "markdown",
                "data": section,
            },
        )

    if doc_id and attrs:
        call_siyuan("/api/attr/setBlockAttrs", {"id": doc_id, "attrs": attrs})

    return {"created": created, "notebook": notebook_id, "path": doc_path, "id": doc_id}


@mcp.tool()
def siyuan_export_doc_markdown(id: str) -> dict[str, Any]:
    """Export a document as Markdown if the SiYuan kernel supports the export endpoint."""
    data = call_siyuan("/api/export/exportMdContent", {"id": id})
    markdown = data
    if isinstance(data, dict):
        markdown = data.get("content") or data.get("markdown") or data
    return {"id": id, "markdown": markdown, "raw": data}


@mcp.tool()
def siyuan_call_api(endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a raw SiYuan /api endpoint. Disabled by default."""
    if not current_allow_raw_api():
        raise PermissionError("Raw API access is disabled. Set SIYUAN_ALLOW_RAW_API=true to enable it.")
    assert_api_endpoint(endpoint)
    data = call_siyuan(endpoint, payload or {})
    return {"endpoint": endpoint, "result": data}


def find_doc_row_by_id(id: str) -> dict[str, Any] | None:
    rows = call_siyuan(
        "/api/query/sql",
        {"stmt": "SELECT id, box, path, hpath, content FROM blocks WHERE type = 'd' AND id = " + sql_string(id)},
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


def flush_transaction() -> None:
    call_siyuan("/api/sqlite/flushTransaction", {})


def public_notebook(notebook: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": notebook.get("id") or notebook.get("box") or notebook.get("notebook"),
        "name": notebook.get("name"),
        "closed": bool(notebook.get("closed")),
    }


def extract_created_id(data: Any) -> str | None:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return None
    return (
        data.get("id")
        or data.get("docID")
        or data.get("blockID")
        or dig(data, "block", "id")
    )


def extract_block_ids(data: Any) -> list[str]:
    if isinstance(data, list):
        ids: list[str] = []
        for item in data:
            if not item:
                continue
            if isinstance(item, str):
                ids.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("id"):
                ids.append(str(item["id"]))
            for operation_key in ("doOperations", "undoOperations"):
                operations = item.get(operation_key)
                if isinstance(operations, list):
                    ids.extend(
                        str(operation["id"])
                        for operation in operations
                        if isinstance(operation, dict) and operation.get("id")
                    )
        return ids
    if isinstance(data, dict):
        blocks = data.get("blocks")
        if isinstance(blocks, list):
            return [str(item.get("id") if isinstance(item, dict) else item) for item in blocks if item]
        ids = data.get("ids")
        if isinstance(ids, list):
            return [str(item) for item in ids if item]
        value = data.get("id") or data.get("blockID")
        return [str(value)] if value else []
    return []


def assert_attr_key(key: str) -> None:
    if not re.match(r"^[A-Za-z0-9_-]+$", key):
        raise ValueError(f"Invalid attribute key: {key}")


def assert_read_only_sql(stmt: str) -> None:
    normalized = re.sub(r"^\s*--.*$", "", stmt.strip(), flags=re.MULTILINE).strip().lower()
    if not re.match(r"^(select|with|pragma)\b", normalized):
        raise ValueError("Only read-only SQL is allowed.")

    forbidden = re.compile(
        r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|vacuum|reindex)\b",
        flags=re.IGNORECASE,
    )
    if forbidden.search(normalized):
        raise ValueError("SQL contains a forbidden write/schema keyword.")


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def dig(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


# Import side effect: registers the siyuan_av_* / siyuan_kmind_* tools on the
# shared mcp instance.
from siyuan_mcp import attributeview as attributeview  # noqa: E402,F401
from siyuan_mcp import kmind as kmind  # noqa: E402,F401
from siyuan_mcp import links as links  # noqa: E402,F401


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
