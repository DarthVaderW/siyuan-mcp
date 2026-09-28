"""AttributeView view tools: render, layout, visibility and column order."""

from __future__ import annotations

from typing import Any, Literal

from siyuan_mcp import core
from siyuan_mcp.attributeview_api import (
    get_attribute_view, render_attribute_view, run_transaction, table_view_operations,
)
from siyuan_mcp.attributeview_values import (
    attribute_view_key_map,
    attribute_view_table_columns,
    attribute_view_view_summary,
    clean_single_line,
    find_attribute_view_key_id,
    normalize_table_view_column_specs,
    require_attribute_view_view,
)
from siyuan_mcp.core import generate_node_id, mcp


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
    return render_attribute_view(
        avId=avId, blockId=blockId, viewId=viewId, page=page,
        pageSize=pageSize, query=query, createIfNotExist=createIfNotExist,
    )


@mcp.tool()
def siyuan_av_set_view_name(
    avId: str,
    viewId: str,
    name: str,
) -> dict[str, Any]:
    """Set the name of one SiYuan database/attribute-view view tab."""
    clean_name = clean_single_line(name, "name")
    attr_view = get_attribute_view(avId)
    require_attribute_view_view(attr_view, viewId)
    raw = run_transaction(
        [
            {
                "action": "setAttrViewViewName",
                "avID": avId,
                "id": viewId,
                "data": clean_name,
            }
        ]
    )
    updated_view = require_attribute_view_view(get_attribute_view(avId), viewId)
    return {
        "avId": avId,
        "viewId": viewId,
        "name": str(updated_view.get("name") or ""),
        "requestedName": clean_name,
        "view": attribute_view_view_summary(updated_view),
        "raw": raw,
    }


@mcp.tool()
def siyuan_av_add_view(
    avId: str,
    blockId: str,
    viewId: str | None = None,
    name: str = "",
    layout: Literal["table", "kanban", "gallery"] = "table",
) -> dict[str, Any]:
    """Add a view tab to a SiYuan database/attribute view."""
    if not blockId.strip():
        raise ValueError("blockId cannot be empty.")
    generated_view_id = viewId or generate_node_id()
    operation: dict[str, Any] = {
        "action": "addAttrViewView",
        "avID": avId,
        "id": generated_view_id,
        "blockID": blockId,
    }
    if layout != "table":
        operation["layout"] = layout
    raw = run_transaction([operation])
    set_name_result = None
    if name.strip():
        set_name_result = siyuan_av_set_view_name(avId, generated_view_id, name)
    attr_view = get_attribute_view(avId)
    view = require_attribute_view_view(attr_view, generated_view_id)
    return {
        "avId": avId,
        "blockId": blockId,
        "viewId": generated_view_id,
        "name": str(view.get("name") or ""),
        "layout": layout,
        "setName": set_name_result,
        "view": attribute_view_view_summary(view),
        "raw": raw,
    }


@mcp.tool()
def siyuan_av_duplicate_view(
    avId: str,
    blockId: str,
    sourceViewId: str,
    viewId: str | None = None,
    name: str = "",
) -> dict[str, Any]:
    """Duplicate one SiYuan database/attribute-view view tab."""
    if not blockId.strip():
        raise ValueError("blockId cannot be empty.")
    attr_view = get_attribute_view(avId)
    require_attribute_view_view(attr_view, sourceViewId)
    generated_view_id = viewId or generate_node_id()
    raw = run_transaction(
        [
            {
                "action": "duplicateAttrViewView",
                "avID": avId,
                "previousID": sourceViewId,
                "id": generated_view_id,
                "blockID": blockId,
            }
        ]
    )
    set_name_result = None
    if name.strip():
        set_name_result = siyuan_av_set_view_name(avId, generated_view_id, name)
    view = require_attribute_view_view(get_attribute_view(avId), generated_view_id)
    return {
        "avId": avId,
        "blockId": blockId,
        "sourceViewId": sourceViewId,
        "viewId": generated_view_id,
        "name": str(view.get("name") or ""),
        "setName": set_name_result,
        "view": attribute_view_view_summary(view),
        "raw": raw,
    }


@mcp.tool()
def siyuan_av_set_active_view(
    avId: str,
    blockId: str,
    viewId: str,
) -> dict[str, Any]:
    """Set which view tab a database/attribute-view block displays."""
    if not blockId.strip():
        raise ValueError("blockId cannot be empty.")
    attr_view = get_attribute_view(avId)
    view = require_attribute_view_view(attr_view, viewId)
    raw = run_transaction(
        [
            {
                "action": "setAttrViewBlockView",
                "blockID": blockId,
                "id": viewId,
                "avID": avId,
            }
        ]
    )
    return {
        "avId": avId,
        "blockId": blockId,
        "viewId": viewId,
        "view": attribute_view_view_summary(view),
        "raw": raw,
    }


@mcp.tool()
def siyuan_av_configure_table_view(
    avId: str,
    blockId: str,
    viewId: str,
    columns: list[Any],
    name: str = "",
    hideUnlisted: bool = True,
    showIcon: bool | None = None,
    wrapField: bool | None = None,
    hideAttrViewName: bool | None = None,
) -> dict[str, Any]:
    """Configure a table view tab: name, active view, column order, visibility, and widths.

    ``columns`` accepts either key ids / key names or objects:
    ``{"keyName": "论文", "width": "360px", "pin": true, "wrap": true}``.
    Unlisted columns are hidden by default, except the primary block key should
    be listed explicitly as the first column in reader-facing views.
    """
    if not blockId.strip():
        raise ValueError("blockId cannot be empty.")
    attr_view = get_attribute_view(avId)
    view = require_attribute_view_view(attr_view, viewId)
    if str(view.get("type") or "") != "table":
        raise ValueError(f"Attribute view view is not table type: {viewId}")
    normalized_columns = normalize_table_view_column_specs(attr_view, columns)
    requested_key_ids = [column["keyId"] for column in normalized_columns]
    key_map = attribute_view_key_map(attr_view)
    current_columns = attribute_view_table_columns(view)

    operations = table_view_operations(
        avId, blockId, viewId, normalized_columns, current_columns,
        find_attribute_view_key_id(attr_view, "block"),
        name=name, hide_unlisted=hideUnlisted, show_icon=showIcon,
        wrap_field=wrapField, hide_attr_view_name=hideAttrViewName,
    )
    raw = run_transaction(operations)
    updated_attr_view = get_attribute_view(avId)
    updated_view = require_attribute_view_view(updated_attr_view, viewId)
    return {
        "avId": avId,
        "blockId": blockId,
        "viewId": viewId,
        "name": str(updated_view.get("name") or ""),
        "configuredColumns": [
            {
                "keyId": key_id,
                "keyName": str(key_map.get(key_id, {}).get("name") or ""),
            }
            for key_id in requested_key_ids
        ],
        "hiddenUnlisted": hideUnlisted,
        "view": attribute_view_view_summary(updated_view),
        "raw": raw,
    }


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
    result = core.call_siyuan("/api/av/sortAttributeViewViewKey", payload)
    return {
        "avId": avId,
        "databaseBlockId": databaseBlockId or None,
        "keyId": keyId,
        "previousKeyId": previousKeyId,
        "raw": result,
    }
