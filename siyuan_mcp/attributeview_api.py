"""Kernel calls and transaction payloads for SiYuan AttributeView."""

from __future__ import annotations

import time
from typing import Any

from siyuan_mcp import core
from siyuan_mcp.attributeview_values import (
    clean_single_line,
    extract_attribute_view_id_from_kramdown,
)


def get_attribute_view(av_id: str) -> dict[str, Any]:
    data = core.call_siyuan("/api/av/getAttributeView", {"id": av_id})
    if isinstance(data, dict) and isinstance(data.get("av"), dict):
        data = data["av"]
    if not isinstance(data, dict):
        raise ValueError(f"Attribute view not found or invalid: {av_id}")
    return data


def run_transaction(do_operations: list[dict[str, Any]]) -> Any:
    if not do_operations:
        raise ValueError("do_operations cannot be empty.")
    return core.call_siyuan(
        "/api/transactions",
        {
            "transactions": [
                {
                    "doOperations": do_operations,
                    "undoOperations": [],
                }
            ],
            "reqId": int(time.time() * 1000),
            "app": "siyuan-mcp",
            "session": "siyuan-mcp",
        },
    )


def get_attribute_view_item_ids_by_bound_ids(av_id: str, block_ids: list[str]) -> dict[str, str]:
    data = core.call_siyuan(
        "/api/av/getAttributeViewItemIDsByBoundIDs",
        {"avID": av_id, "blockIDs": block_ids},
    )
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items() if value}
    return {}


def read_attribute_view_id_from_block(block_id: str) -> str:
    attrs = core.call_siyuan("/api/attr/getBlockAttrs", {"id": block_id}) or {}
    if isinstance(attrs, dict):
        attr_av_id = str(attrs.get("data-av-id") or attrs.get("av-id") or "")
        if attr_av_id:
            return attr_av_id

    kramdown_data = core.call_siyuan("/api/block/getBlockKramdown", {"id": block_id}) or {}
    if isinstance(kramdown_data, dict):
        kramdown = str(kramdown_data.get("kramdown") or "")
    else:
        kramdown = str(kramdown_data)
    return extract_attribute_view_id_from_kramdown(kramdown)


def table_view_operations(
    av_id: str,
    block_id: str,
    view_id: str,
    columns: list[dict[str, Any]],
    current_columns: list[dict[str, Any]],
    primary_key_id: str | None,
    *,
    name: str = "",
    hide_unlisted: bool = True,
    show_icon: bool | None = None,
    wrap_field: bool | None = None,
    hide_attr_view_name: bool | None = None,
) -> list[dict[str, Any]]:
    """Build SiYuan view transactions from already validated column settings."""
    requested_key_ids = [column["keyId"] for column in columns]
    current_key_ids = [str(column.get("id") or "") for column in current_columns if column.get("id")]
    operations: list[dict[str, Any]] = [
        {
            "action": "setAttrViewBlockView",
            "blockID": block_id,
            "id": view_id,
            "avID": av_id,
        }
    ]
    if name.strip():
        operations.append(
            {
                "action": "setAttrViewViewName",
                "avID": av_id,
                "id": view_id,
                "data": clean_single_line(name, "name"),
            }
        )
    if show_icon is not None:
        operations.append(
            {
                "action": "setAttrViewShowIcon",
                "avID": av_id,
                "blockID": block_id,
                "data": bool(show_icon),
                "viewID": view_id,
            }
        )
    if wrap_field is not None:
        operations.append(
            {
                "action": "setAttrViewWrapField",
                "avID": av_id,
                "blockID": block_id,
                "data": bool(wrap_field),
                "viewID": view_id,
            }
        )
    if hide_attr_view_name is not None:
        operations.append(
            {
                "action": "hideAttrViewName",
                "avID": av_id,
                "blockID": block_id,
                "data": bool(hide_attr_view_name),
                "viewID": view_id,
            }
        )

    visible_set = set(requested_key_ids)
    if hide_unlisted:
        for key_id in current_key_ids:
            if key_id == primary_key_id:
                continue
            should_hide = key_id not in visible_set
            current = next((column for column in current_columns if str(column.get("id") or "") == key_id), {})
            if bool(current.get("hidden")) != should_hide:
                operations.append(
                    {
                        "action": "setAttrViewColHidden",
                        "id": key_id,
                        "avID": av_id,
                        "data": should_hide,
                        "blockID": block_id,
                        "viewID": view_id,
                    }
                )

    previous_key_id = ""
    for column in columns:
        key_id = column["keyId"]
        operations.append(
            {
                "action": "sortAttrViewCol",
                "avID": av_id,
                "previousID": previous_key_id,
                "id": key_id,
                "blockID": block_id,
                "viewID": view_id,
            }
        )
        if hide_unlisted:
            operations.append(
                {
                    "action": "setAttrViewColHidden",
                    "id": key_id,
                    "avID": av_id,
                    "data": False,
                    "blockID": block_id,
                    "viewID": view_id,
                }
            )
        if column["width"]:
            operations.append(
                {
                    "action": "setAttrViewColWidth",
                    "id": key_id,
                    "avID": av_id,
                    "data": column["width"],
                    "blockID": block_id,
                    "viewID": view_id,
                }
            )
        if column["pin"] is not None:
            operations.append(
                {
                    "action": "setAttrViewColPin",
                    "id": key_id,
                    "avID": av_id,
                    "data": bool(column["pin"]),
                    "blockID": block_id,
                    "viewID": view_id,
                }
            )
        if column["wrap"] is not None:
            operations.append(
                {
                    "action": "setAttrViewColWrap",
                    "id": key_id,
                    "avID": av_id,
                    "data": bool(column["wrap"]),
                    "blockID": block_id,
                    "viewID": view_id,
                }
            )
        previous_key_id = key_id

    return operations


def render_attribute_view(
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
    data = core.call_siyuan("/api/av/renderAttributeView", payload)
    return {
        "avId": avId,
        "blockId": blockId,
        "viewId": viewId,
        "page": page,
        "pageSize": pageSize,
        "result": data,
    }
