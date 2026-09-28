"""Block content and custom attribute tools."""

from __future__ import annotations

from typing import Any, Literal

from siyuan_mcp import core
from siyuan_mcp.core import mcp


@mcp.tool()
def siyuan_get_block_markdown(id: str) -> dict[str, Any]:
    """Read a block or document as Kramdown/Markdown."""
    data = core.call_siyuan("/api/block/getBlockKramdown", {"id": id})
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
    result = core.call_siyuan(
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
    result = core.call_siyuan("/api/block/updateBlock", {"id": id, "data": data, "dataType": dataType})
    return {"id": id, "updated": True, "raw": result}

@mcp.tool()
def siyuan_delete_block(id: str) -> dict[str, Any]:
    """Delete a block by id."""
    result = core.call_siyuan("/api/block/deleteBlock", {"id": id})
    return {"id": id, "deleted": True, "raw": result}

@mcp.tool()
def siyuan_get_block_attrs(id: str) -> dict[str, Any]:
    """Read custom attributes from a block."""
    attrs = core.call_siyuan("/api/attr/getBlockAttrs", {"id": id})
    return {"id": id, "attrs": attrs}

@mcp.tool()
def siyuan_set_block_attrs(id: str, attrs: dict[str, Any]) -> dict[str, Any]:
    """Set custom attributes on a block."""
    result = core.call_siyuan("/api/attr/setBlockAttrs", {"id": id, "attrs": attrs})
    return {"id": id, "attrs": attrs, "raw": result}

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
