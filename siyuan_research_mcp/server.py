from __future__ import annotations

import argparse
import json
import os
import random
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

VERSION = "0.3.3"
ROOT_DIR = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        os.environ[key] = value


load_dotenv(ROOT_DIR / ".env")

BASE_URL = os.getenv("SIYUAN_BASE_URL", "http://127.0.0.1:6806").rstrip("/")
TOKEN = os.getenv("SIYUAN_TOKEN", "")
DEFAULT_NOTEBOOK = os.getenv("SIYUAN_DEFAULT_NOTEBOOK", "")
CODEX_NOTEBOOK = os.getenv("SIYUAN_CODEX_NOTEBOOK", "20260222005018-okt4cvb")
ALLOW_RAW_API = os.getenv("SIYUAN_ALLOW_RAW_API", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MCP_HOST = os.getenv("SIYUAN_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("SIYUAN_MCP_PORT", "6816"))
MCP_PATH = os.getenv("SIYUAN_MCP_PATH", "/mcp")

mcp = FastMCP("siyuan-mcp", host=MCP_HOST, port=MCP_PORT, streamable_http_path=MCP_PATH)


def request_headers() -> Any:
    try:
        request = mcp.get_context().request_context.request
    except Exception:
        return {}
    return getattr(request, "headers", {}) or {}


def header_value(*names: str) -> str | None:
    headers = request_headers()
    for name in names:
        try:
            value = headers.get(name)
        except AttributeError:
            value = None
        if value:
            return str(value).strip()
    return None


def bearer_token() -> str | None:
    authorization = header_value("authorization")
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() in {"bearer", "token"} and value.strip():
        return value.strip()
    return None


def env_or_header(env_value: str, *headers: str) -> str:
    return header_value(*headers) or env_value


def truthy_header(env_value: bool, *headers: str) -> bool:
    value = header_value(*headers)
    if value is None:
        return env_value
    return value.lower() in {"1", "true", "yes", "on"}


def current_base_url() -> str:
    return env_or_header(
        BASE_URL,
        "x-siyuan-base-url",
        "siyuan-base-url",
    ).rstrip("/")


def current_token() -> str:
    return (
        header_value("x-siyuan-token", "siyuan-token")
        or bearer_token()
        or TOKEN
    )


def current_default_notebook() -> str:
    return env_or_header(
        DEFAULT_NOTEBOOK,
        "x-siyuan-default-notebook",
        "siyuan-default-notebook",
    )


def current_codex_notebook() -> str:
    return env_or_header(
        CODEX_NOTEBOOK,
        "x-siyuan-codex-notebook",
        "siyuan-codex-notebook",
    )


def current_allow_raw_api() -> bool:
    return truthy_header(
        ALLOW_RAW_API,
        "x-siyuan-allow-raw-api",
        "siyuan-allow-raw-api",
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
def siyuan_append_experience_note(
    title: str,
    markdown: str,
    notePath: str = "/MCP/经验库/windows-codex-siyuan-mcp-pitfalls",
    notebook: str | None = None,
) -> dict[str, Any]:
    """Append a reusable Codex/MCP/SiYuan experience note under the experience library."""
    return siyuan_upsert_doc_section(
        path=notePath,
        notebook=notebook or current_codex_notebook(),
        title=title,
        markdown=markdown,
        attrs={
            "custom-type": "codex-experience",
            "custom-project": "siyuan-mcp",
        },
    )


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
def siyuan_av_search(keyword: str = "") -> dict[str, Any]:
    """Search SiYuan database/attribute views by keyword."""
    data = call_siyuan("/api/av/searchAttributeView", {"keyword": keyword})
    return {"keyword": keyword, "result": data}


@mcp.tool()
def siyuan_av_get(avId: str) -> dict[str, Any]:
    """Read a SiYuan attribute view schema/data JSON by id."""
    data = call_siyuan("/api/av/getAttributeView", {"id": avId})
    return {"avId": avId, "result": data}


@mcp.tool()
def siyuan_av_render(
    avId: str,
    blockId: str | None = None,
    viewId: str | None = None,
    page: int = 1,
    pageSize: int = 50,
    query: str = "",
    createIfNotExist: bool = False,
) -> dict[str, Any]:
    """Render a SiYuan database/attribute view."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if pageSize < 1 or pageSize > 200:
        raise ValueError("pageSize must be between 1 and 200")

    payload: dict[str, Any] = {
        "id": avId,
        "page": page,
        "pageSize": pageSize,
        "query": query,
        "createIfNotExist": createIfNotExist,
    }
    if blockId:
        payload["blockID"] = blockId
    if viewId:
        payload["viewID"] = viewId
    data = call_siyuan("/api/av/renderAttributeView", payload)
    return {
        "avId": avId,
        "blockId": blockId,
        "viewId": viewId,
        "page": page,
        "pageSize": pageSize,
        "result": data,
    }


@mcp.tool()
def siyuan_av_add_key(
    avId: str,
    keyName: str,
    keyType: Literal[
        "text",
        "number",
        "date",
        "select",
        "mSelect",
        "url",
        "email",
        "phone",
        "mAsset",
        "checkbox",
        "relation",
    ] = "text",
    keyId: str | None = None,
    keyIcon: str = "",
    previousKeyId: str | None = None,
) -> dict[str, Any]:
    """Add a field/key to a SiYuan attribute view.

    By default the key is appended after the current last key. Pass
    previousKeyId="" explicitly to insert it at the beginning.
    """
    if not keyName.strip():
        raise ValueError("keyName cannot be empty.")
    generated_key_id = keyId or generate_node_id()
    if previousKeyId is None:
        key_ids = attribute_view_key_ids(get_attribute_view(avId))
        previousKeyId = key_ids[-1] if key_ids else ""
    result = call_siyuan(
        "/api/av/addAttributeViewKey",
        {
            "avID": avId,
            "keyID": generated_key_id,
            "keyName": keyName.strip(),
            "keyType": keyType,
            "keyIcon": keyIcon,
            "previousKeyID": previousKeyId,
        },
    )
    return {
        "avId": avId,
        "keyId": generated_key_id,
        "keyName": keyName.strip(),
        "keyType": keyType,
        "raw": result,
    }


@mcp.tool()
def siyuan_av_remove_key(
    avId: str,
    keyId: str,
    removeRelationDest: bool = False,
) -> dict[str, Any]:
    """Remove a field/key from a SiYuan attribute view."""
    result = call_siyuan(
        "/api/av/removeAttributeViewKey",
        {"avID": avId, "keyID": keyId, "removeRelationDest": removeRelationDest},
    )
    return {"avId": avId, "keyId": keyId, "raw": result}


@mcp.tool()
def siyuan_av_sort_key(
    avId: str,
    keyId: str,
    previousKeyId: str = "",
) -> dict[str, Any]:
    """Sort a field/key in the global SiYuan attribute view schema order."""
    result = call_siyuan(
        "/api/av/sortAttributeViewKey",
        {"avID": avId, "keyID": keyId, "previousKeyID": previousKeyId},
    )
    return {"avId": avId, "keyId": keyId, "previousKeyId": previousKeyId, "raw": result}


@mcp.tool()
def siyuan_av_sort_view_key(
    avId: str,
    keyId: str,
    previousKeyId: str = "",
    databaseBlockId: str = "",
) -> dict[str, Any]:
    """Sort a field/key in the current table view column order.

    SiYuan 3.6.5 names the endpoint argument viewID, but the kernel uses the
    database block id to resolve the active view. Leave databaseBlockId empty
    to let SiYuan use the current/default view.
    """
    payload = {"avID": avId, "keyID": keyId, "previousKeyID": previousKeyId}
    if databaseBlockId:
        payload["viewID"] = databaseBlockId
    result = call_siyuan("/api/av/sortAttributeViewViewKey", payload)
    return {
        "avId": avId,
        "databaseBlockId": databaseBlockId or None,
        "keyId": keyId,
        "previousKeyId": previousKeyId,
        "raw": result,
    }


@mcp.tool()
def siyuan_av_append_detached_rows(
    avId: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Append detached rows to a SiYuan attribute view using simple typed values.

    Row shape:
    {
      "itemId": optional stable row/item id,
      "primary": primary block content,
      "values": {"keyID": value}
    }
    """
    if not rows:
        raise ValueError("rows cannot be empty.")
    attr_view = get_attribute_view(avId)
    keys = attribute_view_key_map(attr_view)
    block_key_id = find_attribute_view_key_id(attr_view, "block")
    if not block_key_id:
        raise ValueError(f"Attribute view has no block primary key: {avId}")

    blocks_values: list[list[dict[str, Any]]] = []
    item_ids: list[str] = []
    for row in rows:
        item_id = str(row.get("itemId") or generate_node_id())
        primary = str(row.get("primary") or row.get("title") or row.get("name") or item_id)
        values = row.get("values") or {}
        if not isinstance(values, dict):
            raise ValueError("row.values must be an object mapping key id to value.")

        row_values = [
            build_attribute_view_value(
                key_id=block_key_id,
                key_type="block",
                value=primary,
                item_id=item_id,
            )
        ]
        for key_id, value in values.items():
            key_id = str(key_id)
            if key_id == block_key_id:
                continue
            key = keys.get(key_id)
            if not key:
                raise ValueError(f"Attribute view key not found: {key_id}")
            row_values.append(
                build_attribute_view_value(
                    key_id=key_id,
                    key_type=str(key.get("type") or "text"),
                    value=value,
                    item_id=item_id,
                )
            )

        blocks_values.append(row_values)
        item_ids.append(item_id)

    raw = call_siyuan(
        "/api/av/appendAttributeViewDetachedBlocksWithValues",
        {"avID": avId, "blocksValues": blocks_values},
    )
    return {"avId": avId, "itemIds": item_ids, "rows": len(rows), "raw": raw}


@mcp.tool()
def siyuan_av_ensure_bound_rows(
    avId: str,
    databaseBlockId: str,
    rows: list[dict[str, Any]],
    viewId: str | None = None,
    previousItemId: str = "",
    ignoreDefaultFill: bool = True,
) -> dict[str, Any]:
    """Ensure existing SiYuan blocks/documents are bound as primary-key rows, then set cells.

    Row shape:
    {
      "blockId": existing document/block id used as the primary key,
      "values": {"keyID": value}
    }
    """
    if not rows:
        raise ValueError("rows cannot be empty.")
    bound_block_ids = [str(row["blockId"]) for row in rows]
    existing = get_attribute_view_item_ids_by_bound_ids(avId, bound_block_ids)
    missing = [block_id for block_id in bound_block_ids if not existing.get(block_id)]

    raw_add = None
    if missing:
        payload: dict[str, Any] = {
            "avID": avId,
            "blockID": databaseBlockId,
            "srcs": [{"id": block_id, "isDetached": False} for block_id in missing],
            "previousID": previousItemId,
            "ignoreDefaultFill": ignoreDefaultFill,
        }
        if viewId:
            payload["viewID"] = viewId
        raw_add = call_siyuan("/api/av/addAttributeViewBlocks", payload)
        existing = get_attribute_view_item_ids_by_bound_ids(avId, bound_block_ids)

    cells: list[dict[str, Any]] = []
    for row in rows:
        block_id = str(row["blockId"])
        item_id = existing.get(block_id)
        if not item_id:
            raise ValueError(f"Could not resolve item id for bound block: {block_id}")
        values = row.get("values") or {}
        if not isinstance(values, dict):
            raise ValueError("row.values must be an object mapping key id to value.")
        for key_id, value in values.items():
            cells.append({"itemId": item_id, "keyId": str(key_id), "value": value})

    raw_cells = siyuan_av_batch_set_cells(avId, cells)["raw"] if cells else None
    return {
        "avId": avId,
        "databaseBlockId": databaseBlockId,
        "boundBlockIds": bound_block_ids,
        "addedBlockIds": missing,
        "itemIdsByBlockId": existing,
        "cellUpdates": len(cells),
        "rawAdd": raw_add,
        "rawCells": raw_cells,
    }


@mcp.tool()
def siyuan_av_set_cell(
    avId: str,
    keyId: str,
    itemId: str,
    value: Any,
) -> dict[str, Any]:
    """Set one cell in a SiYuan attribute view using a simple typed value."""
    attr_view = get_attribute_view(avId)
    keys = attribute_view_key_map(attr_view)
    key = keys.get(keyId)
    if not key:
        raise ValueError(f"Attribute view key not found: {keyId}")
    typed_value = build_attribute_view_value(
        key_id=keyId,
        key_type=str(key.get("type") or "text"),
        value=value,
        item_id=itemId,
    )
    data = call_siyuan(
        "/api/av/setAttributeViewBlockAttr",
        {"avID": avId, "keyID": keyId, "itemID": itemId, "value": typed_value},
    )
    return {"avId": avId, "keyId": keyId, "itemId": itemId, "value": typed_value, "raw": data}


@mcp.tool()
def siyuan_av_batch_set_cells(
    avId: str,
    cells: list[dict[str, Any]],
) -> dict[str, Any]:
    """Set multiple cells in a SiYuan attribute view using simple typed values."""
    if not cells:
        raise ValueError("cells cannot be empty.")
    attr_view = get_attribute_view(avId)
    keys = attribute_view_key_map(attr_view)
    values = []
    for cell in cells:
        key_id = str(cell["keyId"])
        item_id = str(cell["itemId"])
        key = keys.get(key_id)
        if not key:
            raise ValueError(f"Attribute view key not found: {key_id}")
        values.append(
            {
                "keyID": key_id,
                "itemID": item_id,
                "value": build_attribute_view_value(
                    key_id=key_id,
                    key_type=str(key.get("type") or "text"),
                    value=cell.get("value"),
                    item_id=item_id,
                ),
            }
        )
    data = call_siyuan("/api/av/batchSetAttributeViewBlockAttrs", {"avID": avId, "values": values})
    return {"avId": avId, "cells": len(cells), "raw": data}


@mcp.tool()
def siyuan_call_api(endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a raw SiYuan /api endpoint. Disabled by default."""
    if not current_allow_raw_api():
        raise PermissionError("Raw API access is disabled. Set SIYUAN_ALLOW_RAW_API=true to enable it.")
    assert_api_endpoint(endpoint)
    data = call_siyuan(endpoint, payload or {})
    return {"endpoint": endpoint, "result": data}


def call_siyuan(endpoint: str, payload: dict[str, Any] | None = None) -> Any:
    assert_api_endpoint(endpoint)
    base_url = current_base_url()
    token = current_token()
    if not token:
        raise RuntimeError("SIYUAN_TOKEN is not configured.")

    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        base_url + endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {token}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SiYuan HTTP {error.code} for {endpoint}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cannot reach SiYuan at {base_url}: {error.reason}") from error

    try:
        decoded = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return text

    if isinstance(decoded, dict) and isinstance(decoded.get("code"), int) and decoded["code"] != 0:
        raise RuntimeError(
            f"SiYuan API error {decoded['code']} for {endpoint}: "
            f"{decoded.get('msg') or stable_json(decoded)}"
        )

    if isinstance(decoded, dict) and "data" in decoded:
        return decoded["data"]
    return decoded


def find_notebook(id_or_name: str | None) -> dict[str, Any] | None:
    if not id_or_name:
        return None

    data = call_siyuan("/api/notebook/lsNotebooks", {})
    for notebook in extract_notebooks(data):
        if notebook.get("id") == id_or_name or notebook.get("name") == id_or_name:
            return notebook
    return None


def resolve_notebook_id(id_or_name: str | None = None) -> str:
    candidate = id_or_name or current_default_notebook()
    if not candidate:
        raise ValueError("Notebook is required. Provide notebook or set SIYUAN_DEFAULT_NOTEBOOK.")

    notebook = find_notebook(candidate)
    return str(notebook.get("id") if notebook else candidate)


def get_doc_id_by_path(notebook_id: str, path: str) -> str | None:
    data = call_siyuan(
        "/api/filetree/getIDsByHPath",
        {
            "notebook": notebook_id,
            "path": normalize_doc_path(path),
        },
    )

    if isinstance(data, list):
        first = data[0] if data else None
        return first.get("id") if isinstance(first, dict) else first

    if isinstance(data, dict):
        ids = data.get("ids")
        if isinstance(ids, list):
            first = ids[0] if ids else None
            return first.get("id") if isinstance(first, dict) else first
        return data.get("id")

    return None


def get_hpath_by_id(id: str) -> str | None:
    data = call_siyuan("/api/filetree/getHPathByID", {"id": id})
    return str(data) if data else None


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


def extract_notebooks(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("notebooks", "boxes"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


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


def get_attribute_view(av_id: str) -> dict[str, Any]:
    data = call_siyuan("/api/av/getAttributeView", {"id": av_id})
    if isinstance(data, dict) and isinstance(data.get("av"), dict):
        data = data["av"]
    if not isinstance(data, dict):
        raise ValueError(f"Attribute view not found or invalid: {av_id}")
    return data


def attribute_view_key_map(attr_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    key_map: dict[str, dict[str, Any]] = {}
    for key_values in attr_view.get("keyValues") or []:
        if not isinstance(key_values, dict):
            continue
        key = key_values.get("key")
        if isinstance(key, dict) and key.get("id"):
            key_map[str(key["id"])] = key
    return key_map


def attribute_view_key_ids(attr_view: dict[str, Any]) -> list[str]:
    key_ids = attr_view.get("keyIDs")
    if isinstance(key_ids, list) and key_ids:
        return [str(key_id) for key_id in key_ids if key_id]
    return list(attribute_view_key_map(attr_view).keys())


def find_attribute_view_key_id(attr_view: dict[str, Any], key_type: str) -> str | None:
    for key_id, key in attribute_view_key_map(attr_view).items():
        if key.get("type") == key_type:
            return key_id
    return None


def get_attribute_view_item_ids_by_bound_ids(av_id: str, block_ids: list[str]) -> dict[str, str]:
    data = call_siyuan(
        "/api/av/getAttributeViewItemIDsByBoundIDs",
        {"avID": av_id, "blockIDs": block_ids},
    )
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items() if value}
    return {}


def build_attribute_view_value(
    key_id: str,
    key_type: str,
    value: Any,
    item_id: str | None = None,
) -> dict[str, Any]:
    if isinstance(value, dict) and any(
        field in value
        for field in (
            "block",
            "text",
            "number",
            "date",
            "mSelect",
            "url",
            "email",
            "phone",
            "mAsset",
            "checkbox",
            "relation",
            "rollup",
        )
    ):
        typed = dict(value)
        typed.setdefault("keyID", key_id)
        if item_id:
            typed.setdefault("blockID", item_id)
        typed.setdefault("type", key_type)
        return typed

    typed_value: dict[str, Any] = {"keyID": key_id, "type": key_type}
    if item_id:
        typed_value["blockID"] = item_id

    if key_type == "block":
        if isinstance(value, dict):
            content = str(value.get("content") or value.get("name") or value.get("title") or "")
            bound_id = str(value.get("id") or "")
            typed_value["isDetached"] = not bool(bound_id)
            typed_value["block"] = {"id": bound_id, "content": content}
        else:
            typed_value["isDetached"] = True
            typed_value["block"] = {"content": str(value or "")}
    elif key_type == "text":
        typed_value["text"] = {"content": "" if value is None else str(value)}
    elif key_type == "number":
        number = float(value) if value not in (None, "") else 0.0
        formatted = format(number, "g") if value not in (None, "") else ""
        typed_value["number"] = {
            "content": number,
            "isNotEmpty": value not in (None, ""),
            "format": "",
            "formattedContent": formatted,
        }
    elif key_type == "date":
        typed_value["date"] = coerce_attribute_view_date(value)
    elif key_type in {"select", "mSelect"}:
        values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
        typed_value["mSelect"] = [
            {
                "content": str(item.get("content") if isinstance(item, dict) else item),
                "color": str(item.get("color", "")) if isinstance(item, dict) else "",
            }
            for item in values
            if str(item.get("content") if isinstance(item, dict) else item)
        ]
    elif key_type == "url":
        typed_value["url"] = {"content": "" if value is None else str(value)}
    elif key_type == "email":
        typed_value["email"] = {"content": "" if value is None else str(value)}
    elif key_type == "phone":
        typed_value["phone"] = {"content": "" if value is None else str(value)}
    elif key_type == "checkbox":
        typed_value["checkbox"] = {"checked": bool(value)}
    elif key_type == "relation":
        block_ids = value
        if isinstance(value, dict):
            block_ids = value.get("blockIDs") or []
        if isinstance(block_ids, str):
            block_ids = [block_ids]
        typed_value["relation"] = {"blockIDs": [str(item) for item in (block_ids or [])], "contents": None}
    elif key_type == "mAsset":
        assets = value if isinstance(value, list) else ([] if value in (None, "") else [value])
        typed_value["mAsset"] = [
            {
                "type": str(item.get("type", "file")) if isinstance(item, dict) else "file",
                "name": str(item.get("name", item.get("content", ""))) if isinstance(item, dict) else str(item),
                "content": str(item.get("content", "")) if isinstance(item, dict) else str(item),
            }
            for item in assets
        ]
    else:
        raise ValueError(f"Unsupported or read-only attribute view key type: {key_type}")

    return typed_value


def coerce_attribute_view_date(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {"content": 0, "isNotEmpty": False, "content2": 0, "isNotEmpty2": False}
    if isinstance(value, (int, float)):
        millis = int(value)
    else:
        text = str(value)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            millis = int(datetime.fromisoformat(text).timestamp() * 1000)
        elif re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", text):
            millis = int(datetime.fromisoformat(text.replace(" ", "T")).timestamp() * 1000)
        else:
            raise ValueError("Date values must be epoch milliseconds, YYYY-MM-DD, or YYYY-MM-DD HH:MM.")
    return {
        "content": millis,
        "isNotEmpty": True,
        "content2": 0,
        "isNotEmpty2": False,
        "isNotTime": True,
        "hasEndDate": False,
        "formattedContent": datetime.fromtimestamp(millis / 1000).strftime("%Y-%m-%d"),
    }


def generate_node_id() -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    suffix = "".join(random.choice(alphabet) for _ in range(7))
    return datetime.now().strftime("%Y%m%d%H%M%S") + "-" + suffix


def normalize_doc_path(value: str) -> str:
    clean = re.sub(r"/+", "/", value.strip().replace("\\", "/"))
    if not clean:
        raise ValueError("Document path cannot be empty.")
    return clean if clean.startswith("/") else f"/{clean}"


def assert_api_endpoint(endpoint: str) -> None:
    if not endpoint.startswith("/api/"):
        raise ValueError("Endpoint must start with /api/.")
    if ".." in endpoint:
        raise ValueError("Endpoint cannot contain '..'.")


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


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SiYuan MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.getenv("SIYUAN_MCP_TRANSPORT", "stdio"),
        help="MCP transport. Use streamable-http for Codex UI URL mode.",
    )
    parser.add_argument("--host", default=MCP_HOST, help="HTTP host for streamable-http.")
    parser.add_argument("--port", type=int, default=MCP_PORT, help="HTTP port for streamable-http.")
    parser.add_argument("--path", default=MCP_PATH, help="HTTP MCP path for streamable-http.")
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.settings.streamable_http_path = args.path
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
