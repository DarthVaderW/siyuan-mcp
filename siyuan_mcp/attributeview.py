"""SiYuan AttributeView (database) tools.

Importing this module registers the ``siyuan_av_*`` tools on the shared
``mcp`` instance from :mod:`siyuan_mcp.core`.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime
from typing import Any, Literal

from siyuan_mcp.core import call_siyuan, generate_node_id, mcp


ATTRIBUTE_VIEW_KEY_TYPES = {
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
}

SELECT_COLOR_PALETTE = [str(index) for index in range(1, 15)]


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


def _append_unique_key_id(key_ids: list[str], key_id: Any) -> None:
    normalized = str(key_id or "")
    if normalized and normalized not in key_ids:
        key_ids.append(normalized)


def attribute_view_column_key_ids(attr_view: dict[str, Any]) -> list[str]:
    key_ids: list[str] = []
    for view in attr_view.get("views") or []:
        if not isinstance(view, dict):
            continue
        columns = view.get("columns")
        if isinstance(columns, list):
            for column in columns:
                if isinstance(column, dict):
                    _append_unique_key_id(key_ids, column.get("id"))
        table = view.get("table")
        if not isinstance(table, dict):
            continue
        for column in table.get("columns") or []:
            if isinstance(column, dict):
                _append_unique_key_id(key_ids, column.get("id"))
    return key_ids


def attribute_view_key_ids(attr_view: dict[str, Any]) -> list[str]:
    ordered_key_ids = attribute_view_column_key_ids(attr_view)
    key_ids = attr_view.get("keyIDs")
    if isinstance(key_ids, list) and key_ids:
        for key_id in key_ids:
            _append_unique_key_id(ordered_key_ids, key_id)
    for key_id in attribute_view_key_map(attr_view).keys():
        _append_unique_key_id(ordered_key_ids, key_id)
    return ordered_key_ids


def attribute_view_name(attr_view: dict[str, Any]) -> str:
    return str(attr_view.get("name") or attr_view.get("Name") or "")


def find_attribute_view_key_id(attr_view: dict[str, Any], key_type: str) -> str | None:
    for key_id, key in attribute_view_key_map(attr_view).items():
        if key.get("type") == key_type:
            return key_id
    return None


def relation_target_av_id(key: dict[str, Any]) -> str:
    relation = key.get("relation")
    if not isinstance(relation, dict):
        return ""
    return str(relation.get("avID") or relation.get("avId") or relation.get("id") or "")


def run_transaction(do_operations: list[dict[str, Any]]) -> Any:
    if not do_operations:
        raise ValueError("do_operations cannot be empty.")
    return call_siyuan(
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
    data = call_siyuan(
        "/api/av/getAttributeViewItemIDsByBoundIDs",
        {"avID": av_id, "blockIDs": block_ids},
    )
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items() if value}
    return {}


def get_attribute_view_bound_ids_by_item_ids(attr_view: dict[str, Any]) -> dict[str, str]:
    block_key_id = find_attribute_view_key_id(attr_view, "block")
    if not block_key_id:
        return {}
    bound: dict[str, str] = {}
    key_values = attr_view.get("keyValues") or []
    for key_value in key_values:
        if not isinstance(key_value, dict):
            continue
        key = key_value.get("key")
        if not isinstance(key, dict) or str(key.get("id") or "") != block_key_id:
            continue
        for value in key_value.get("values") or []:
            if not isinstance(value, dict):
                continue
            item_id = str(value.get("blockID") or "")
            block = value.get("block")
            if not item_id or not isinstance(block, dict):
                continue
            bound_id = str(block.get("id") or "")
            if bound_id:
                bound[item_id] = bound_id
    return bound


def select_option_colors(key: dict[str, Any]) -> dict[str, str]:
    colors: dict[str, str] = {}
    for option in key.get("options") or []:
        if not isinstance(option, dict):
            continue
        name = str(option.get("name") or option.get("content") or "")
        color = str(option.get("color") or "")
        if name and color:
            colors[name] = color
    return colors


def stable_select_color(content: str, index: int = 0) -> str:
    if not content:
        return SELECT_COLOR_PALETTE[index % len(SELECT_COLOR_PALETTE)]
    total = sum(ord(char) for char in content)
    return SELECT_COLOR_PALETTE[(total + index) % len(SELECT_COLOR_PALETTE)]


def normalize_select_values(key: dict[str, Any], value: Any) -> list[dict[str, str]]:
    values = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    existing_colors = select_option_colors(key)
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(values):
        if isinstance(item, dict):
            content = str(item.get("content") or item.get("name") or "")
            color = str(item.get("color") or "")
        else:
            content = str(item)
            color = ""
        if not content:
            continue
        if not color:
            color = existing_colors.get(content) or stable_select_color(content, index)
        normalized.append({"content": content, "color": color})
    return normalized


def normalize_id_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if str(item or "")]


def rendered_relation_values(data: Any, key_id: str, item_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(data, dict):
        relation = data.get("relation")
        if (
            isinstance(relation, dict)
            and str(data.get("keyID") or data.get("keyId") or "") == key_id
            and str(data.get("blockID") or data.get("blockId") or data.get("itemID") or data.get("itemId") or "")
            == item_id
        ):
            found.append(data)
        for child in data.values():
            found.extend(rendered_relation_values(child, key_id, item_id))
    elif isinstance(data, list):
        for child in data:
            found.extend(rendered_relation_values(child, key_id, item_id))
    return found


def relation_contents_count(values: list[dict[str, Any]]) -> int:
    count = 0
    for value in values:
        relation = value.get("relation")
        if not isinstance(relation, dict):
            continue
        contents = relation.get("contents")
        if isinstance(contents, list):
            count += len(contents)
    return count


def extract_inserted_block_ids(data: Any) -> list[str]:
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
            operations = item.get("doOperations")
            if isinstance(operations, list):
                ids.extend(
                    str(operation["id"])
                    for operation in operations
                    if isinstance(operation, dict) and operation.get("id")
                )
            if not ids:
                undo_operations = item.get("undoOperations")
                if isinstance(undo_operations, list):
                    ids.extend(
                        str(operation["id"])
                        for operation in undo_operations
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


def extract_attribute_view_id_from_kramdown(markdown: str) -> str:
    match = re.search(r"""data-av-id=(["'])(?P<id>[^"']+)\1""", markdown)
    return html.unescape(match.group("id")) if match else ""


def read_attribute_view_id_from_block(block_id: str) -> str:
    attrs = call_siyuan("/api/attr/getBlockAttrs", {"id": block_id}) or {}
    if isinstance(attrs, dict):
        attr_av_id = str(attrs.get("data-av-id") or attrs.get("av-id") or "")
        if attr_av_id:
            return attr_av_id

    kramdown_data = call_siyuan("/api/block/getBlockKramdown", {"id": block_id}) or {}
    if isinstance(kramdown_data, dict):
        kramdown = str(kramdown_data.get("kramdown") or "")
    else:
        kramdown = str(kramdown_data)
    return extract_attribute_view_id_from_kramdown(kramdown)


def build_attribute_view_value(
    key_id: str,
    key_type: str,
    value: Any,
    item_id: str | None = None,
    key: dict[str, Any] | None = None,
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
        typed_value["mSelect"] = normalize_select_values(key or {}, value)
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


def normalize_create_table_fields(fields: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for field in fields or []:
        if not isinstance(field, dict):
            raise ValueError("fields items must be objects.")
        name = str(field.get("name") or field.get("keyName") or "").strip()
        if not name:
            raise ValueError("field name cannot be empty.")
        key_type = str(field.get("type") or field.get("keyType") or "text")
        if key_type not in ATTRIBUTE_VIEW_KEY_TYPES:
            raise ValueError(f"Unsupported attribute view key type: {key_type}")
        key_id = str(field.get("id") or field.get("keyId") or "")
        key_icon = str(field.get("icon") or field.get("keyIcon") or "")
        normalized.append(
            {
                "name": name,
                "type": key_type,
                "id": key_id,
                "icon": key_icon,
                "relationTargetAvId": str(field.get("relationTargetAvId") or field.get("targetAvId") or ""),
                "relationBackKeyId": str(field.get("relationBackKeyId") or field.get("backKeyId") or ""),
                "relationBackKeyName": str(field.get("relationBackKeyName") or field.get("backKeyName") or ""),
                "relationTwoWay": bool(field.get("relationTwoWay") or field.get("isTwoWay") or False),
            }
        )
    return normalized


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
def siyuan_av_set_name(
    avId: str,
    name: str,
) -> dict[str, Any]:
    """Set the human-visible name of a SiYuan database/attribute view."""
    clean_name = name.strip().replace("\n", " ")
    if not clean_name:
        raise ValueError("name cannot be empty.")
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
    raw_insert = call_siyuan(endpoint, {"parentID": parentId, "data": dom, "dataType": "dom"})
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
    raw = call_siyuan(
        "/api/av/setAttributeViewBlockAttr",
        {"avID": avId, "keyID": keyId, "itemID": itemId, "value": typed_value},
    )

    render_validation: dict[str, Any] | None = None
    if validateRender:
        rendered = siyuan_av_render(
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
    data = call_siyuan("/api/av/batchSetAttributeViewBlockAttrs", {"avID": avId, "values": values})
    return {"avId": avId, "cells": len(cells), "raw": data}


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
