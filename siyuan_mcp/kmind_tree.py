"""KMind tree operations, style rules, outlines and diffs; no filesystem or MCP registration."""

from __future__ import annotations

import html
import random
import re
from datetime import datetime
from typing import Any




SAFE_NODE_STYLE_FIELDS = {
    "fillColor",
    "color",
    "borderColor",
    "borderWidth",
    "borderRadius",
    "fontSize",
    "fontWeight",
    "shape",
    "paddingX",
    "paddingY",
}


LINE_STYLE_FIELDS = {"lineColor", "lineWidth"}


CONTENT_FIELDS = {
    "text",
    "note",
    "hyperlink",
    "hyperlinkTitle",
    "image",
    "imageTitle",
    "imageSize",
    "icon",
    "tag",
    "generalization",
}


def kmind_html_text(value: Any) -> str:
    """Strip the HTML-ish rich text of a node down to plain text."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    return html.unescape(text).strip()


def make_rich_text(text: str) -> str:
    return f"<p>{html.escape(text, quote=False)}</p>"


def node_uid(node: dict[str, Any]) -> str | None:
    data = node.get("data") if isinstance(node, dict) else None
    return data.get("uid") if isinstance(data, dict) else None


def node_plain_text(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node, dict) else None
    return kmind_html_text(data.get("text")) if isinstance(data, dict) else ""


def walk_kmind_nodes(root: dict[str, Any]):
    """Yield (node, depth, path_texts) for every node, depth-first from root."""
    stack: list[tuple[dict[str, Any], int, tuple[str, ...]]] = [(root, 0, ())]
    while stack:
        node, depth, path = stack.pop()
        yield node, depth, path
        children = node.get("children") or []
        child_path = path + (node_plain_text(node),)
        for child in reversed(children):
            if isinstance(child, dict):
                stack.append((child, depth + 1, child_path))


def find_node_by_uid(root: dict[str, Any], uid: str) -> dict[str, Any] | None:
    for node, _depth, _path in walk_kmind_nodes(root):
        if node_uid(node) == uid:
            return node
    return None


def find_nodes_by_text(root: dict[str, Any], text: str) -> list[dict[str, Any]]:
    target = text.strip()
    return [node for node, _d, _p in walk_kmind_nodes(root) if node_plain_text(node) == target]


def count_nodes(root: dict[str, Any]) -> int:
    return sum(1 for _ in walk_kmind_nodes(root))


def generate_kmind_uid() -> str:
    now = datetime.now()
    stamp = now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"
    suffix = "".join(random.choice("0123456789abcdef") for _ in range(8))
    return f"kmind-node-{stamp}-{suffix}"


def make_node(text: str, node_style: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "text": make_rich_text(text),
        "uid": generate_kmind_uid(),
        "richText": True,
        "expand": True,
    }
    if node_style:
        apply_node_style(data, node_style)
    return {"data": data, "children": []}


def apply_node_style(
    data: dict[str, Any],
    node_style: dict[str, Any] | None,
    line_style: dict[str, Any] | None = None,
) -> list[str]:
    """Apply style fields onto a node's data dict. Returns the changed field names.

    Only SAFE_NODE_STYLE_FIELDS are accepted from node_style. Branch line fields
    (lineColor/lineWidth) are only changed when line_style is explicitly given.
    """
    changed: list[str] = []
    for key, value in (node_style or {}).items():
        if key not in SAFE_NODE_STYLE_FIELDS:
            raise ValueError(
                f"Unsupported node_style field: {key}. "
                f"Allowed: {sorted(SAFE_NODE_STYLE_FIELDS)}. "
                "Use line_style for lineColor/lineWidth."
            )
        data[key] = value
        changed.append(key)
    for key, value in (line_style or {}).items():
        if key not in LINE_STYLE_FIELDS:
            raise ValueError(f"Unsupported line_style field: {key}. Allowed: {sorted(LINE_STYLE_FIELDS)}.")
        data[key] = value
        changed.append(key)
    return changed


def build_outline(root: dict[str, Any], max_depth: int | None, include_styles: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node, depth, _path in walk_kmind_nodes(root):
        if max_depth is not None and depth > max_depth:
            continue
        entry: dict[str, Any] = {
            "uid": node_uid(node),
            "depth": depth,
            "text": node_plain_text(node),
        }
        if include_styles:
            data = node.get("data", {})
            entry["style"] = {
                k: data[k] for k in (SAFE_NODE_STYLE_FIELDS | LINE_STYLE_FIELDS) if k in data
            }
        items.append(entry)
    return items


def build_outline_markdown(root: dict[str, Any], max_depth: int | None) -> str:
    lines: list[str] = []
    for node, depth, _path in walk_kmind_nodes(root):
        if max_depth is not None and depth > max_depth:
            continue
        lines.append("  " * depth + "- " + node_plain_text(node))
    return "\n".join(lines)


def classify_kmind_field(field: str) -> str:
    """Bucket a node-data field name: content / nodeStyle / branchLine / other."""
    if field in LINE_STYLE_FIELDS:
        return "branchLine"
    if field in SAFE_NODE_STYLE_FIELDS:
        return "nodeStyle"
    if field in CONTENT_FIELDS:
        return "content"
    return "other"


def _index_nodes_by_uid(root: dict[str, Any]) -> tuple[dict[str, tuple[dict[str, Any], list[str]]], int]:
    """{uid: (node, ancestor_texts)} for every uid-bearing node; count the rest."""
    out: dict[str, tuple[dict[str, Any], list[str]]] = {}
    no_uid = 0
    for node, _depth, path_texts in walk_kmind_nodes(root):
        uid = node_uid(node)
        if uid is None:
            no_uid += 1
            continue
        out[uid] = (node, [p for p in path_texts if p])
    return out, no_uid


def diff_kmind_trees(ref_root: dict[str, Any], cur_root: dict[str, Any]) -> dict[str, Any]:
    """Pure node-level diff (reference -> current), pairing nodes by uid.

    Returns ``added`` / ``removed`` / ``changed`` plus a ``summary``. Each changed
    node lists its changed field names bucketed into content / nodeStyle /
    branchLine / other, with the before/after value of each changed field, so
    style and branch-line changes are unmissable. No live SiYuan, no IO.
    """
    ref_nodes, ref_no_uid = _index_nodes_by_uid(ref_root)
    cur_nodes, cur_no_uid = _index_nodes_by_uid(cur_root)
    ref_uids, cur_uids = set(ref_nodes), set(cur_nodes)

    def entry(uid: str, table: dict[str, tuple[dict[str, Any], list[str]]]) -> dict[str, Any]:
        node, ancestors = table[uid]
        text = node_plain_text(node)
        return {"uid": uid, "text": text, "path": ancestors + [text]}

    added = [entry(uid, cur_nodes) for uid in cur_uids - ref_uids]
    removed = [entry(uid, ref_nodes) for uid in ref_uids - cur_uids]

    field_changes = {"content": 0, "nodeStyle": 0, "branchLine": 0, "other": 0}
    changed: list[dict[str, Any]] = []
    for uid in ref_uids & cur_uids:
        ref_data = ref_nodes[uid][0].get("data") or {}
        cur_data = cur_nodes[uid][0].get("data") or {}
        fields = sorted(
            key for key in set(ref_data) | set(cur_data)
            if (key in ref_data) != (key in cur_data) or ref_data.get(key) != cur_data.get(key)
        )
        if not fields:
            continue
        buckets: dict[str, list[str]] = {"content": [], "nodeStyle": [], "branchLine": [], "other": []}
        values: dict[str, dict[str, Any]] = {}
        for field in fields:
            bucket = classify_kmind_field(field)
            buckets[bucket].append(field)
            field_changes[bucket] += 1
            values[field] = {
                "before": ref_data.get(field),
                "after": cur_data.get(field),
                "beforePresent": field in ref_data,
                "afterPresent": field in cur_data,
            }
        item = entry(uid, cur_nodes)
        item["changedFields"] = buckets
        item["values"] = values
        changed.append(item)

    for group in (added, removed, changed):
        group.sort(key=lambda e: e["uid"])

    summary = {
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
        "fieldChangesByBucket": field_changes,
        "branchLineChanged": field_changes["branchLine"] > 0,
        "nodeStyleChanged": field_changes["nodeStyle"] > 0,
    }
    if ref_no_uid or cur_no_uid:
        summary["nodesSkippedNoUid"] = {"reference": ref_no_uid, "current": cur_no_uid}
    return {"added": added, "removed": removed, "changed": changed, "summary": summary}


def require_root(data: dict[str, Any]) -> dict[str, Any]:
    root = data.get("root")
    if not isinstance(root, dict):
        raise ValueError("KMind file has no valid root node.")
    return root


def locate_parent_node(
    root: dict[str, Any],
    parent_uid: str | None,
    parent_text: str | None,
) -> dict[str, Any]:
    if parent_uid:
        node = find_node_by_uid(root, parent_uid)
        if not node:
            raise ValueError(f"Parent node not found by uid: {parent_uid}")
        return node
    if parent_text:
        matches = find_nodes_by_text(root, parent_text)
        if not matches:
            raise ValueError(f"Parent node not found by text: {parent_text}")
        if len(matches) > 1:
            raise ValueError(
                f"parent_text '{parent_text}' matches {len(matches)} nodes; "
                "use parent_uid to disambiguate."
            )
        return matches[0]
    return root


def locate_target_node(
    root: dict[str, Any],
    node_uid_arg: str | None,
    node_text: str | None,
) -> dict[str, Any]:
    if node_uid_arg:
        node = find_node_by_uid(root, node_uid_arg)
        if not node:
            raise ValueError(f"Node not found by uid: {node_uid_arg}")
        return node
    if node_text:
        matches = find_nodes_by_text(root, node_text)
        if not matches:
            raise ValueError(f"Node not found by text: {node_text}")
        if len(matches) > 1:
            raise ValueError(
                f"node_text '{node_text}' matches {len(matches)} nodes; "
                "use node_uid to disambiguate."
            )
        return matches[0]
    raise ValueError("Provide node_uid or node_text.")
