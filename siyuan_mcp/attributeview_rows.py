"""AttributeView row binding, relation resolution and cell write tools."""

from __future__ import annotations
from typing import Any

from siyuan_mcp import core
from siyuan_mcp.attributeview_api import (
    render_attribute_view,
    get_attribute_view,
    get_attribute_view_item_ids_by_bound_ids,
)
from siyuan_mcp.attributeview_values import (
    attribute_view_key_map,
    build_attribute_view_value,
    find_attribute_view_key_id,
    normalize_id_list,
    relation_contents_count,
    relation_target_av_id,
    rendered_relation_values,
)
from siyuan_mcp.core import generate_node_id, mcp


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

    raw = core.call_siyuan(
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
        raw_add = core.call_siyuan("/api/av/addAttributeViewBlocks", payload)
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
def siyuan_av_set_relation_cell(
    avId: str,
    keyId: str,
    itemId: str,
    targetBlockIds: list[str] | None = None,
    targetItemIds: list[str] | None = None,
    validateRender: bool = True,
    requireRenderedContents: bool = False,
    blockId: str | None = None,
    viewId: str | None = None,
) -> dict[str, Any]:
    """Set a relation cell using target row item ids, resolving docs when needed.

    Native SiYuan relation cells store target AttributeView row item ids. They
    do not store target document block ids. Pass ``targetBlockIds`` for normal
    use; the tool resolves those document ids through the relation target AV.
    Pass ``targetItemIds`` only when the target row ids are already known.
    """
    attr_view = get_attribute_view(avId)
    key = attribute_view_key_map(attr_view).get(keyId)
    if not key:
        raise ValueError(f"Attribute view key not found: {keyId}")
    if key.get("type") != "relation":
        raise ValueError(f"Attribute view key is not relation type: {keyId}")
    target_av_id = relation_target_av_id(key)
    if not target_av_id:
        raise ValueError(
            "Relation key has no target AttributeView. Run siyuan_av_configure_relation first."
        )

    requested_target_item_ids = normalize_id_list(targetItemIds)
    requested_target_block_ids = normalize_id_list(targetBlockIds)
    target_item_ids = list(requested_target_item_ids)
    item_ids_by_block_id: dict[str, str] = {}
    missing_target_block_ids: list[str] = []
    if requested_target_block_ids:
        item_ids_by_block_id = get_attribute_view_item_ids_by_bound_ids(target_av_id, requested_target_block_ids)
        missing_target_block_ids = [
            block_id for block_id in requested_target_block_ids if not item_ids_by_block_id.get(block_id)
        ]
        if missing_target_block_ids:
            raise ValueError(
                "Could not resolve target AttributeView row item ids for block ids: "
                + ", ".join(missing_target_block_ids)
            )
        target_item_ids.extend(item_ids_by_block_id[block_id] for block_id in requested_target_block_ids)

    target_item_ids = list(dict.fromkeys(target_item_ids))
    warnings: list[str] = []
    typed_value = build_attribute_view_value(
        key_id=keyId,
        key_type="relation",
        value={"blockIDs": target_item_ids},
        item_id=itemId,
        key=key,
    )
    raw = core.call_siyuan(
        "/api/av/setAttributeViewBlockAttr",
        {"avID": avId, "keyID": keyId, "itemID": itemId, "value": typed_value},
    )

    render_validation: dict[str, Any] | None = None
    if validateRender:
        rendered = render_attribute_view(
            avId,
            blockId=blockId,
            viewId=viewId,
            page=1,
            pageSize=200,
        )
        relation_values = rendered_relation_values(rendered.get("result"), keyId, itemId)
        contents_count = relation_contents_count(relation_values)
        render_validation = {
            "checked": True,
            "relationValueCount": len(relation_values),
            "relationContentsCount": contents_count,
            "ok": not target_item_ids or contents_count > 0,
        }
        if target_item_ids and contents_count < 1:
            message = (
                "Relation cell was written but rendered relation.contents was not found on the rendered page. "
                "Pass blockId/viewId for the concrete table view, or requireRenderedContents=true in small "
                "acceptance tests when a missing rendered relation should fail hard."
            )
            if requireRenderedContents:
                raise ValueError(message)
            warnings.append(message)

    return {
        "avId": avId,
        "keyId": keyId,
        "itemId": itemId,
        "targetAvId": target_av_id,
        "targetBlockIds": requested_target_block_ids,
        "targetItemIds": target_item_ids,
        "itemIdsByBlockId": item_ids_by_block_id,
        "value": typed_value,
        "renderValidation": render_validation,
        "warnings": warnings,
        "raw": raw,
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
    key_type = str(key.get("type") or "text")
    if key_type == "relation":
        raise ValueError("Use siyuan_av_set_relation_cell for relation fields.")
    typed_value = build_attribute_view_value(
        key_id=keyId,
        key_type=key_type,
        value=value,
        item_id=itemId,
        key=key,
    )
    data = core.call_siyuan(
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
        key_type = str(key.get("type") or "text")
        if key_type == "relation":
            raise ValueError("Use siyuan_av_set_relation_cell for relation fields.")
        values.append(
            {
                "keyID": key_id,
                "itemID": item_id,
                "value": build_attribute_view_value(
                    key_id=key_id,
                    key_type=key_type,
                    value=cell.get("value"),
                    item_id=item_id,
                    key=key,
                ),
            }
        )
    data = core.call_siyuan("/api/av/batchSetAttributeViewBlockAttrs", {"avID": avId, "values": values})
    return {"avId": avId, "cells": len(cells), "raw": data}
