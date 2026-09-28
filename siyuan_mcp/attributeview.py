"""AttributeView creation, field schema and summary tools."""

from __future__ import annotations

import html
from typing import Any, Literal

from siyuan_mcp import core
from siyuan_mcp.attributeview_api import (
    get_attribute_view,
    read_attribute_view_id_from_block,
    run_transaction,
)
from siyuan_mcp.attributeview_values import (
    attribute_view_key_ids,
    attribute_view_key_map,
    attribute_view_name,
    clean_single_line,
    extract_inserted_block_ids,
    get_attribute_view_bound_ids_by_item_ids,
    normalize_create_table_fields,
    relation_target_av_id,
)
from siyuan_mcp.attributeview_views import siyuan_av_render
from siyuan_mcp.core import generate_node_id, mcp


@mcp.tool()
def siyuan_av_search(keyword: str = "") -> dict[str, Any]:
    """Search SiYuan database/attribute views by keyword."""
    data = core.call_siyuan("/api/av/searchAttributeView", {"keyword": keyword})
    return {"keyword": keyword, "result": data}


@mcp.tool()
def siyuan_av_get(avId: str) -> dict[str, Any]:
    """Read a SiYuan attribute view schema/data JSON by id."""
    data = core.call_siyuan("/api/av/getAttributeView", {"id": avId})
    return {"avId": avId, "result": data}


@mcp.tool()
def siyuan_av_set_name(
    avId: str,
    name: str,
) -> dict[str, Any]:
    """Set the human-visible name of a SiYuan database/attribute view."""
    clean_name = clean_single_line(name, "name")
    raw = run_transaction(
        [
            {
                "action": "setAttrViewName",
                "id": avId,
                "data": clean_name,
            }
        ]
    )
    attr_view = get_attribute_view(avId)
    return {
        "avId": avId,
        "name": attribute_view_name(attr_view),
        "requestedName": clean_name,
        "raw": raw,
    }


@mcp.tool()
def siyuan_av_create_table(
    parentId: str,
    name: str = "",
    fields: list[dict[str, Any]] | None = None,
    avId: str | None = None,
    position: Literal["append", "prepend"] = "append",
    removeDefaultSelect: bool = True,
) -> dict[str, Any]:
    """Create and initialize a table AttributeView block under a parent block.

    This is a convenience wrapper around: insert a NodeAttributeView block,
    render it with createIfNotExist=true, optionally remove SiYuan's default
    "单选" field, then append caller-provided fields.
    """
    if not parentId.strip():
        raise ValueError("parentId cannot be empty.")
    generated_av_id = avId or generate_node_id()
    normalized_fields = normalize_create_table_fields(fields)
    dom = (
        '<div data-type="NodeAttributeView" '
        f'data-av-id="{html.escape(generated_av_id, quote=True)}" '
        'data-av-type="table"></div>'
    )
    endpoint = "/api/block/prependBlock" if position == "prepend" else "/api/block/appendBlock"
    raw_insert = core.call_siyuan(endpoint, {"parentID": parentId, "data": dom, "dataType": "dom"})
    inserted = extract_inserted_block_ids(raw_insert)
    if not inserted:
        raise RuntimeError("Could not resolve inserted AttributeView block id.")
    database_block_id = inserted[0]

    rendered = siyuan_av_render(
        generated_av_id,
        blockId=database_block_id,
        createIfNotExist=True,
        page=1,
        pageSize=50,
    )
    actual_av_id = read_attribute_view_id_from_block(database_block_id) or generated_av_id
    warnings: list[str] = []
    if actual_av_id != generated_av_id:
        warnings.append("Inserted AttributeView block reported a different av id; using the block's av id.")
        rendered = siyuan_av_render(
            actual_av_id,
            blockId=database_block_id,
            createIfNotExist=True,
            page=1,
            pageSize=50,
        )

    result = rendered.get("result") if isinstance(rendered, dict) else {}
    if not isinstance(result, dict):
        result = {}
    view = result.get("view")
    if not isinstance(view, dict):
        view = {}
    view_id = str(result.get("viewID") or view.get("id") or "")
    columns = view.get("columns") if isinstance(view, dict) else []
    primary_key_id = ""
    default_select_key_id = ""
    previous_key_id = ""
    for column in columns or []:
        if not isinstance(column, dict):
            continue
        column_id = str(column.get("id") or "")
        if column.get("type") == "block":
            primary_key_id = column_id
            previous_key_id = column_id
        elif not default_select_key_id and column.get("type") == "select":
            default_select_key_id = column_id

    if not primary_key_id:
        warnings.append("Could not identify the AttributeView primary block key; new fields were inserted at the beginning.")

    removed_default_select = False
    if removeDefaultSelect and default_select_key_id:
        siyuan_av_remove_key(actual_av_id, default_select_key_id)
        removed_default_select = True

    set_name_result = None
    if name.strip():
        set_name_result = siyuan_av_set_name(actual_av_id, name)

    added_fields: list[dict[str, Any]] = []
    for field in normalized_fields:
        add_result = siyuan_av_add_key(
            actual_av_id,
            field["name"],
            keyType=field["type"],  # type: ignore[arg-type]
            keyId=field["id"] or None,
            keyIcon=field["icon"],
            previousKeyId=previous_key_id,
            relationTargetAvId=field["relationTargetAvId"] or None,
            relationTwoWay=bool(field["relationTwoWay"]),
            relationBackKeyId=field["relationBackKeyId"] or None,
            relationBackKeyName=field["relationBackKeyName"],
        )
        added_fields.append(add_result)
        previous_key_id = add_result["keyId"]

    return {
        "avId": actual_av_id,
        "requestedAvId": generated_av_id,
        "name": set_name_result["name"] if isinstance(set_name_result, dict) else None,
        "requestedName": name.strip() or None,
        "databaseBlockId": database_block_id,
        "viewId": view_id or None,
        "primaryKeyId": primary_key_id or None,
        "removedDefaultSelect": removed_default_select,
        "setName": set_name_result,
        "addedFields": added_fields,
        "warnings": warnings,
        "rawInsert": raw_insert,
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
    relationTargetAvId: str | None = None,
    relationTwoWay: bool = False,
    relationBackKeyId: str | None = None,
    relationBackKeyName: str = "",
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
    result = core.call_siyuan(
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
    relation = None
    if keyType == "relation" and relationTargetAvId:
        relation = siyuan_av_configure_relation(
            avId,
            generated_key_id,
            relationTargetAvId,
            isTwoWay=relationTwoWay,
            backRelationKeyId=relationBackKeyId,
            backRelationKeyName=relationBackKeyName,
            keyName=keyName.strip(),
        )
    return {
        "avId": avId,
        "keyId": generated_key_id,
        "keyName": keyName.strip(),
        "keyType": keyType,
        "relation": relation,
        "raw": result,
    }


@mcp.tool()
def siyuan_av_configure_relation(
    avId: str,
    keyId: str,
    targetAvId: str,
    isTwoWay: bool = False,
    backRelationKeyId: str | None = None,
    backRelationKeyName: str = "",
    keyName: str = "",
) -> dict[str, Any]:
    """Configure a relation field so it points at another AttributeView.

    This only configures the field schema. Cell values still need target row
    item ids; use ``siyuan_av_set_relation_cell`` for that instead of writing
    raw document block ids into a relation cell.
    """
    if not targetAvId.strip():
        raise ValueError("targetAvId cannot be empty.")
    attr_view = get_attribute_view(avId)
    key = attribute_view_key_map(attr_view).get(keyId)
    if not key:
        raise ValueError(f"Attribute view key not found: {keyId}")
    if key.get("type") != "relation":
        raise ValueError(f"Attribute view key is not relation type: {keyId}")
    clean_key_name = keyName.strip() or str(key.get("name") or "").strip()
    if not clean_key_name:
        raise ValueError("keyName cannot be empty for relation configuration.")
    clean_back_key_id = backRelationKeyId or (generate_node_id() if isTwoWay else "")
    raw = run_transaction(
        [
            {
                "action": "updateAttrViewColRelation",
                "avID": avId,
                "id": targetAvId.strip(),
                "keyID": keyId,
                "isTwoWay": isTwoWay,
                "backRelationKeyID": clean_back_key_id,
                "name": backRelationKeyName.strip(),
                "format": clean_key_name,
            }
        ]
    )
    updated_key = attribute_view_key_map(get_attribute_view(avId)).get(keyId, {})
    return {
        "avId": avId,
        "keyId": keyId,
        "targetAvId": relation_target_av_id(updated_key),
        "isTwoWay": isTwoWay,
        "backRelationKeyId": clean_back_key_id or None,
        "raw": raw,
    }


@mcp.tool()
def siyuan_av_remove_key(
    avId: str,
    keyId: str,
    removeRelationDest: bool = False,
) -> dict[str, Any]:
    """Remove a field/key from a SiYuan attribute view."""
    result = core.call_siyuan(
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
    result = core.call_siyuan(
        "/api/av/sortAttributeViewKey",
        {"avID": avId, "keyID": keyId, "previousKeyID": previousKeyId},
    )
    return {"avId": avId, "keyId": keyId, "previousKeyId": previousKeyId, "raw": result}


@mcp.tool()
def siyuan_av_summary(
    avId: str,
    includeRows: bool = True,
) -> dict[str, Any]:
    """Return a compact, agent-friendly summary of an AttributeView.

    Use this before updating schemas or relation cells. It avoids dumping the
    full AttributeView JSON while preserving the IDs agents actually need.
    """
    attr_view = get_attribute_view(avId)
    key_ids = attribute_view_key_ids(attr_view)
    keys = attribute_view_key_map(attr_view)
    key_summaries: list[dict[str, Any]] = []
    for key_id in key_ids:
        key = keys.get(key_id, {})
        options = []
        for option in key.get("options") or []:
            if not isinstance(option, dict):
                continue
            options.append(
                {
                    "name": str(option.get("name") or option.get("content") or ""),
                    "color": str(option.get("color") or ""),
                }
            )
        key_summaries.append(
            {
                "id": key_id,
                "name": str(key.get("name") or ""),
                "type": str(key.get("type") or ""),
                "relationTargetAvId": relation_target_av_id(key),
                "options": options or None,
            }
        )

    views = []
    for view in attr_view.get("views") or []:
        if not isinstance(view, dict):
            continue
        views.append(
            {
                "id": str(view.get("id") or ""),
                "name": str(view.get("name") or ""),
                "type": str(view.get("type") or ""),
            }
        )

    item_ids_by_bound_id: dict[str, str] = {}
    bound_ids_by_item_id: dict[str, str] = {}
    if includeRows:
        bound_ids_by_item_id = get_attribute_view_bound_ids_by_item_ids(attr_view)
        item_ids_by_bound_id = {block_id: item_id for item_id, block_id in bound_ids_by_item_id.items()}

    return {
        "avId": avId,
        "name": attribute_view_name(attr_view),
        "keys": key_summaries,
        "views": views,
        "rowCount": len(bound_ids_by_item_id) if includeRows else None,
        "itemIdsByBoundId": item_ids_by_bound_id if includeRows else None,
        "boundIdsByItemId": bound_ids_by_item_id if includeRows else None,
    }


@mcp.tool()
def siyuan_av_validate_schema(
    avId: str,
    requireName: bool = True,
    requireRelationTargets: bool = True,
    requireSelectColors: bool = True,
) -> dict[str, Any]:
    """Check common AttributeView schema problems that make the SiYuan UI poor."""
    summary = siyuan_av_summary(avId, includeRows=False)
    issues: list[dict[str, str]] = []
    if requireName and not str(summary.get("name") or "").strip():
        issues.append(
            {
                "severity": "error",
                "code": "missing-av-name",
                "message": "AttributeView internal name is empty; SiYuan will show 未命名数据库.",
            }
        )
    for key in summary.get("keys") or []:
        if not isinstance(key, dict):
            continue
        key_type = str(key.get("type") or "")
        key_id = str(key.get("id") or "")
        key_name = str(key.get("name") or "")
        if requireRelationTargets and key_type == "relation" and not str(key.get("relationTargetAvId") or ""):
            issues.append(
                {
                    "severity": "error",
                    "code": "relation-without-target-av",
                    "message": f"Relation key {key_name or key_id} has no target AttributeView.",
                }
            )
        if requireSelectColors and key_type in {"select", "mSelect"}:
            for option in key.get("options") or []:
                if isinstance(option, dict) and str(option.get("name") or "") and not str(option.get("color") or ""):
                    issues.append(
                        {
                            "severity": "warning",
                            "code": "select-option-empty-color",
                            "message": f"Select option {option.get('name')} on key {key_name or key_id} has empty color.",
                        }
                    )
    return {"avId": avId, "ok": not any(issue["severity"] == "error" for issue in issues), "issues": issues}
