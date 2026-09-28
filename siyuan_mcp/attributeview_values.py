"""Pure AttributeView schema inspection, validation and cell-value encoding."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any




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


def attribute_view_views(attr_view: dict[str, Any]) -> list[dict[str, Any]]:
    return [view for view in attr_view.get("views") or [] if isinstance(view, dict)]


def find_attribute_view_view(attr_view: dict[str, Any], view_id: str) -> dict[str, Any] | None:
    for view in attribute_view_views(attr_view):
        if str(view.get("id") or "") == view_id:
            return view
    return None


def attribute_view_table_columns(view: dict[str, Any]) -> list[dict[str, Any]]:
    table = view.get("table")
    if not isinstance(table, dict):
        return []
    return [column for column in table.get("columns") or [] if isinstance(column, dict)]


def attribute_view_view_summary(view: dict[str, Any]) -> dict[str, Any]:
    columns = attribute_view_table_columns(view)
    return {
        "id": str(view.get("id") or ""),
        "name": str(view.get("name") or ""),
        "type": str(view.get("type") or ""),
        "hideAttrViewName": bool(view.get("hideAttrViewName")),
        "pageSize": view.get("pageSize"),
        "columns": [
            {
                "id": str(column.get("id") or ""),
                "hidden": bool(column.get("hidden")),
                "pin": bool(column.get("pin")),
                "wrap": bool(column.get("wrap")),
                "width": str(column.get("width") or ""),
            }
            for column in columns
        ],
    }


def find_attribute_view_key_id(attr_view: dict[str, Any], key_type: str) -> str | None:
    for key_id, key in attribute_view_key_map(attr_view).items():
        if key.get("type") == key_type:
            return key_id
    return None


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


def relation_target_av_id(key: dict[str, Any]) -> str:
    relation = key.get("relation")
    if not isinstance(relation, dict):
        return ""
    return str(relation.get("avID") or relation.get("avId") or relation.get("id") or "")


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


def clean_single_line(value: str, field_name: str) -> str:
    clean_value = value.strip().replace("\n", " ")
    if not clean_value:
        raise ValueError(f"{field_name} cannot be empty.")
    return clean_value


def require_attribute_view_view(attr_view: dict[str, Any], view_id: str) -> dict[str, Any]:
    view = find_attribute_view_view(attr_view, view_id)
    if not view:
        raise ValueError(f"Attribute view view not found: {view_id}")
    return view


def resolve_attribute_view_key_id(attr_view: dict[str, Any], column: Any) -> str:
    keys = attribute_view_key_map(attr_view)
    if isinstance(column, str):
        candidate = column.strip()
        if not candidate:
            raise ValueError("column name/id cannot be empty.")
        if candidate in keys:
            return candidate
        matches = [key_id for key_id, key in keys.items() if str(key.get("name") or "") == candidate]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Attribute view column name is ambiguous: {candidate}")
        raise ValueError(f"Attribute view column not found: {candidate}")
    if not isinstance(column, dict):
        raise ValueError("column must be a string or object.")
    candidate = str(column.get("keyId") or column.get("id") or "").strip()
    if candidate:
        if candidate not in keys:
            raise ValueError(f"Attribute view column id not found: {candidate}")
        return candidate
    name = str(column.get("keyName") or column.get("name") or "").strip()
    if not name:
        candidates = column.get("keyNameCandidates") or column.get("nameCandidates") or []
        if isinstance(candidates, list):
            for item in candidates:
                try:
                    return resolve_attribute_view_key_id(attr_view, str(item))
                except ValueError:
                    continue
        raise ValueError("column object must include keyId/id, keyName/name, or keyNameCandidates/nameCandidates.")
    return resolve_attribute_view_key_id(attr_view, name)


def normalize_table_view_column_specs(
    attr_view: dict[str, Any],
    columns: list[Any],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for column in columns:
        key_id = resolve_attribute_view_key_id(attr_view, column)
        if key_id in seen:
            continue
        seen.add(key_id)
        spec = column if isinstance(column, dict) else {}
        normalized.append(
            {
                "keyId": key_id,
                "width": str(spec.get("width") or ""),
                "pin": spec.get("pin"),
                "wrap": spec.get("wrap"),
                "hidden": spec.get("hidden"),
            }
        )
    if not normalized:
        raise ValueError("columns cannot be empty.")
    return normalized


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
