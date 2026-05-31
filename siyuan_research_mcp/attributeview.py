"""SiYuan AttributeView (database) tools.

Importing this module registers the ``siyuan_av_*`` tools on the shared
``mcp`` instance from :mod:`siyuan_research_mcp.core`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from siyuan_research_mcp.core import call_siyuan, generate_node_id, mcp


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
