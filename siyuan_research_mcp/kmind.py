"""SiYuan KMind (mind-map) tools.

KMind data is not an independent service: a KMind page is a SiYuan ``.sy``
document whose ``custom-data-assets-kmind-doctree-doc`` property points at a
JSON ``.kmind`` file under ``<dataDir>/assets``. These tools provide low-level,
safe primitives over that JSON (read/export/search/add/style) with optimistic
concurrency (sha256) and automatic backups for writes.

Workflow decisions (e.g. how to classify papers) belong in skills, not here.
Importing this module registers the ``siyuan_kmind_*`` tools on the shared
``mcp`` instance from :mod:`siyuan_research_mcp.core`.
"""

from __future__ import annotations

import hashlib
import html
import json
import random
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from siyuan_research_mcp.core import call_siyuan, current_default_notebook, mcp

# --- Constants ---------------------------------------------------------------

DOC_KMIND_ASSET_ATTR = "custom-data-assets-kmind-doctree-doc"
BACKUP_REL_DIR = ("storage", "codex-kmind-backups")
BACKUP_INDEX_NAME = "backup_index.json"

# Node styles that are safe to change without affecting surrounding branches.
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
# Branch/connector line styles. Only touched when line_style is given explicitly.
LINE_STYLE_FIELDS = {"lineColor", "lineWidth"}

# Retention limits for the KMind backup directory.
MAX_BACKUPS_PER_DOC = 20
MAX_BACKUP_AGE_DAYS = 30
MAX_BACKUP_TOTAL_BYTES = 100 * 1024 * 1024


# --- SiYuan resolution -------------------------------------------------------


def find_siyuan_data_dir() -> Path:
    conf = call_siyuan("/api/system/getConf", {})
    system = (conf or {}).get("conf", {}).get("system", {}) if isinstance(conf, dict) else {}
    data_dir = system.get("dataDir") or (
        str(Path(system["workspaceDir"]) / "data") if system.get("workspaceDir") else None
    )
    if not data_dir:
        raise RuntimeError("Could not resolve SiYuan data directory from /api/system/getConf.")
    return Path(data_dir)


def _resolve_notebook_id(id_or_name: str | None) -> str:
    candidate = id_or_name or current_default_notebook()
    if not candidate:
        raise ValueError("Notebook is required. Provide notebook or set SIYUAN_DEFAULT_NOTEBOOK.")
    data = call_siyuan("/api/notebook/lsNotebooks", {})
    notebooks = data.get("notebooks") if isinstance(data, dict) else data
    for notebook in notebooks or []:
        if isinstance(notebook, dict) and (
            notebook.get("id") == candidate or notebook.get("name") == candidate
        ):
            return str(notebook["id"])
    return str(candidate)


def _doc_id_by_path(notebook_id: str, path: str) -> str | None:
    clean = re.sub(r"/+", "/", path.strip().replace("\\", "/"))
    clean = clean if clean.startswith("/") else f"/{clean}"
    data = call_siyuan("/api/filetree/getIDsByHPath", {"notebook": notebook_id, "path": clean})
    if isinstance(data, list) and data:
        first = data[0]
        return first.get("id") if isinstance(first, dict) else first
    if isinstance(data, dict):
        ids = data.get("ids")
        if isinstance(ids, list) and ids:
            first = ids[0]
            return first.get("id") if isinstance(first, dict) else first
        return data.get("id")
    return None


def _doc_hpath(doc_id: str) -> str | None:
    data = call_siyuan("/api/filetree/getHPathByID", {"id": doc_id})
    return str(data) if data else None


def resolve_kmind_doc(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the KMind asset for a SiYuan document and return its metadata."""
    if doc_id:
        resolved_id = doc_id
        notebook_id = None
    elif path:
        notebook_id = _resolve_notebook_id(notebook)
        resolved_id = _doc_id_by_path(notebook_id, path)
        if not resolved_id:
            raise ValueError(f"Document not found for path: {path}")
    else:
        raise ValueError("Provide doc_id or path.")

    attrs = call_siyuan("/api/attr/getBlockAttrs", {"id": resolved_id})
    if not isinstance(attrs, dict):
        attrs = {}
    asset_rel = attrs.get(DOC_KMIND_ASSET_ATTR)
    if not asset_rel:
        raise ValueError(
            f"Document {resolved_id} has no KMind asset "
            f"({DOC_KMIND_ASSET_ATTR} attribute missing). Is it a KMind document?"
        )

    data_dir = find_siyuan_data_dir()
    asset_abs = (data_dir / asset_rel).resolve()
    # Path-traversal guard: the asset must stay inside the data dir and be .kmind.
    if not str(asset_abs).startswith(str(data_dir.resolve())):
        raise ValueError("Resolved KMind asset escapes the SiYuan data directory.")
    if asset_abs.suffix != ".kmind":
        raise ValueError(f"Resolved asset is not a .kmind file: {asset_rel}")

    title = attrs.get("custom-kmind-doctree-doc-init-title")
    hpath = _doc_hpath(resolved_id)
    exists = asset_abs.exists()
    sha256 = size_bytes = None
    if exists:
        raw = asset_abs.read_bytes()
        sha256 = _sha256(raw)
        size_bytes = len(raw)

    return {
        "docId": resolved_id,
        "docPath": hpath,
        "notebook": notebook_id or attrs.get("box"),
        "title": title or (hpath.rsplit("/", 1)[-1] if hpath else None),
        "assetRelPath": asset_rel,
        "assetAbsPath": str(asset_abs),
        "exists": exists,
        "sha256": sha256,
        "sizeBytes": size_bytes,
    }


# --- KMind file IO -----------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_kmind(asset_abs: str | Path) -> tuple[dict[str, Any], str, int]:
    raw = Path(asset_abs).read_bytes()
    return json.loads(raw.decode("utf-8")), _sha256(raw), len(raw)


def dump_kmind_bytes(data: dict[str, Any]) -> bytes:
    # KMind writes compact JSON (no whitespace); match it to avoid reformat churn.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# --- Node helpers ------------------------------------------------------------


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


def _outline(root: dict[str, Any], max_depth: int | None, include_styles: bool) -> list[dict[str, Any]]:
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


def _outline_markdown(root: dict[str, Any], max_depth: int | None) -> str:
    lines: list[str] = []
    for node, depth, _path in walk_kmind_nodes(root):
        if max_depth is not None and depth > max_depth:
            continue
        lines.append("  " * depth + "- " + node_plain_text(node))
    return "\n".join(lines)


# --- Backups -----------------------------------------------------------------


def _backup_dir(data_dir: Path) -> Path:
    return data_dir.joinpath(*BACKUP_REL_DIR)


def _load_backup_index(backup_dir: Path) -> list[dict[str, Any]]:
    index_path = backup_dir / BACKUP_INDEX_NAME
    if not index_path.exists():
        return []
    try:
        loaded = json.loads(index_path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, list) else []
    except json.JSONDecodeError:
        return []


def _save_backup_index(backup_dir: Path, index: list[dict[str, Any]]) -> None:
    (backup_dir / BACKUP_INDEX_NAME).write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cleanup_kmind_backups(backup_dir: Path, index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enforce per-doc count, age, and total-size limits. Oldest removed first."""
    kept = list(index)
    removed: list[dict[str, Any]] = []

    def drop(entry: dict[str, Any]) -> None:
        kept.remove(entry)
        removed.append(entry)
        target = backup_dir / entry.get("backupPath", "")
        if target.name and target.exists():
            target.unlink()

    # Age limit.
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_BACKUP_AGE_DAYS)
    for entry in list(kept):
        created = entry.get("createdAt")
        try:
            ts = datetime.fromisoformat(created) if created else None
        except ValueError:
            ts = None
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                drop(entry)

    # Per-document count limit (oldest first).
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for entry in kept:
        by_doc.setdefault(entry.get("docId", ""), []).append(entry)
    for entries in by_doc.values():
        entries.sort(key=lambda e: e.get("createdAt", ""))
        while len(entries) > MAX_BACKUPS_PER_DOC:
            drop(entries.pop(0))

    # Total-size limit (oldest first across all docs).
    def total_size() -> int:
        return sum(int(e.get("sizeBytes") or 0) for e in kept)

    kept.sort(key=lambda e: e.get("createdAt", ""))
    age_ordered = list(kept)
    while total_size() > MAX_BACKUP_TOTAL_BYTES and age_ordered:
        drop(age_ordered.pop(0))

    return kept


def write_backup(
    data_dir: Path,
    asset_abs: Path,
    asset_rel: str,
    doc_id: str,
    operation: str,
    sha256_before: str,
    size_bytes: int,
    timestamp: str,
) -> str:
    backup_dir = _backup_dir(data_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = f"{timestamp}__{doc_id}__before-{operation}.kmind"
    shutil.copy2(asset_abs, backup_dir / backup_name)

    index = _load_backup_index(backup_dir)
    index.append(
        {
            "source": asset_rel,
            "docId": doc_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "sha256Before": sha256_before,
            "sizeBytes": size_bytes,
            "backupPath": backup_name,
        }
    )
    index = cleanup_kmind_backups(backup_dir, index)
    _save_backup_index(backup_dir, index)
    return backup_name


# --- Write guard (optimistic concurrency) ------------------------------------


def _write_with_guard(
    meta: dict[str, Any],
    operation: str,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
    expected_sha256: str | None,
    backup: bool,
    dry_run: bool,
) -> dict[str, Any]:
    asset_abs = Path(meta["assetAbsPath"])
    if not asset_abs.exists():
        raise FileNotFoundError(f"KMind asset not found on disk: {asset_abs}")

    data, sha_before, size_before = load_kmind(asset_abs)
    if expected_sha256 and expected_sha256 != sha_before:
        raise ValueError(
            f"sha256 mismatch for {meta['docId']}: expected {expected_sha256}, "
            f"on-disk {sha_before}. Re-read the KMind file before writing."
        )

    detail = mutate(data)
    new_bytes = dump_kmind_bytes(data)  # also validates JSON-serializability
    json.loads(new_bytes.decode("utf-8"))  # validate round-trip

    base = {
        "docId": meta["docId"],
        "operation": operation,
        "sha256Before": sha_before,
        **detail,
    }
    if dry_run:
        base["dryRun"] = True
        base["wouldWriteBytes"] = len(new_bytes)
        return base

    # Re-read just before writing to catch a concurrent UI edit during processing.
    current = asset_abs.read_bytes()
    if _sha256(current) != sha_before:
        raise ValueError(
            "KMind file changed on disk during processing; aborting to avoid "
            "overwriting a concurrent edit. Re-read and retry."
        )

    backup_name = None
    if backup:
        backup_name = write_backup(
            data_dir=find_siyuan_data_dir(),
            asset_abs=asset_abs,
            asset_rel=meta["assetRelPath"],
            doc_id=meta["docId"],
            operation=operation,
            sha256_before=sha_before,
            size_bytes=size_before,
            timestamp=datetime.now().strftime("%Y%m%d-%H%M%S"),
        )

    asset_abs.write_bytes(new_bytes)
    base["dryRun"] = False
    base["sha256After"] = _sha256(new_bytes)
    base["sizeBytes"] = len(new_bytes)
    base["backup"] = backup_name
    return base


def _require_root(data: dict[str, Any]) -> dict[str, Any]:
    root = data.get("root")
    if not isinstance(root, dict):
        raise ValueError("KMind file has no valid root node.")
    return root


def _locate_parent(
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


def _locate_target(
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


# --- Tools -------------------------------------------------------------------


@mcp.tool()
def siyuan_kmind_find(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Find a KMind document's asset metadata by SiYuan path or document id."""
    return resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)


@mcp.tool()
def siyuan_kmind_read(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
    max_depth: int = 3,
    include_styles: bool = False,
) -> dict[str, Any]:
    """Read and summarize a KMind file as an outline (read-only, no backup)."""
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)
    data, sha256, size_bytes = load_kmind(meta["assetAbsPath"])
    root = _require_root(data)
    return {
        "docId": meta["docId"],
        "title": meta["title"],
        "sha256": sha256,
        "sizeBytes": size_bytes,
        "root": {"uid": node_uid(root), "text": node_plain_text(root)},
        "nodeCount": count_nodes(root),
        "maxDepth": max_depth,
        "outline": _outline(root, max_depth, include_styles),
    }


@mcp.tool()
def siyuan_kmind_export_outline(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
    max_depth: int | None = None,
) -> dict[str, Any]:
    """Export a KMind file as a Markdown bullet outline (read-only, no backup)."""
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)
    data, sha256, _size = load_kmind(meta["assetAbsPath"])
    root = _require_root(data)
    return {
        "docId": meta["docId"],
        "sha256": sha256,
        "markdown": _outline_markdown(root, max_depth),
    }


@mcp.tool()
def siyuan_kmind_search_nodes(
    query: str,
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Search KMind nodes by text; returns uid and the path from root (read-only)."""
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)
    data, _sha, _size = load_kmind(meta["assetAbsPath"])
    root = _require_root(data)
    needle = query if case_sensitive else query.lower()
    matches: list[dict[str, Any]] = []
    for node, _depth, path_texts in walk_kmind_nodes(root):
        text = node_plain_text(node)
        haystack = text if case_sensitive else text.lower()
        if needle in haystack:
            full_path = [p for p in path_texts if p] + [text]
            matches.append({"uid": node_uid(node), "text": text, "path": full_path})
    return {"docId": meta["docId"], "query": query, "matches": matches}


@mcp.tool()
def siyuan_kmind_add_node(
    text: str,
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
    parent_uid: str | None = None,
    parent_text: str | None = None,
    children: list[str] | None = None,
    node_style: dict[str, Any] | None = None,
    dry_run: bool = False,
    expected_sha256: str | None = None,
    backup: bool = True,
) -> dict[str, Any]:
    """Add a child node (optionally with children) under a parent node or the root.

    parent_uid is preferred; parent_text is allowed only when it matches exactly
    one node; if neither is given the node is added under root. Writes create a
    backup unless dry_run=True. Pass expected_sha256 for optimistic locking.
    """
    if not text.strip():
        raise ValueError("text cannot be empty.")
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        root = _require_root(data)
        parent = _locate_parent(root, parent_uid, parent_text)
        new_node = make_node(text, node_style)
        for child_text in children or []:
            if str(child_text).strip():
                new_node["children"].append(make_node(str(child_text)))
        parent.setdefault("children", []).append(new_node)
        return {
            "addedUid": node_uid(new_node),
            "parentUid": node_uid(parent),
            "text": text,
            "childCount": len(new_node["children"]),
        }

    return _write_with_guard(meta, "add-node", mutate, expected_sha256, backup, dry_run)


@mcp.tool()
def siyuan_kmind_style_node(
    node_style: dict[str, Any],
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
    node_uid: str | None = None,
    node_text: str | None = None,
    line_style: dict[str, Any] | None = None,
    dry_run: bool = False,
    expected_sha256: str | None = None,
    backup: bool = True,
) -> dict[str, Any]:
    """Style one node. Branch line color/width are untouched unless line_style is given.

    Target the node by node_uid (preferred) or node_text (must match one node).
    Only fillColor/color/borderColor/borderWidth/borderRadius/fontSize/fontWeight/
    shape/paddingX/paddingY are accepted in node_style.
    """
    if not node_style and not line_style:
        raise ValueError("Provide node_style and/or line_style.")
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        root = _require_root(data)
        target = _locate_target(root, node_uid, node_text)
        changed = apply_node_style(target["data"], node_style, line_style)
        return {
            "styledUid": target.get("data", {}).get("uid"),
            "changedFields": changed,
            "touchedLineStyle": bool(line_style),
        }

    return _write_with_guard(meta, "style-node", mutate, expected_sha256, backup, dry_run)


@mcp.tool()
def siyuan_kmind_validate(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Validate that a KMind asset is well-formed JSON with a root node (read-only)."""
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)
    try:
        data, sha256, size_bytes = load_kmind(meta["assetAbsPath"])
    except json.JSONDecodeError as error:
        return {"docId": meta["docId"], "valid": False, "error": f"Invalid JSON: {error}"}
    root = data.get("root")
    valid = isinstance(root, dict) and isinstance(root.get("data"), dict)
    return {
        "docId": meta["docId"],
        "valid": valid,
        "sha256": sha256,
        "sizeBytes": size_bytes,
        "nodeCount": count_nodes(root) if valid else 0,
        "topLevelKeys": sorted(data.keys()) if isinstance(data, dict) else [],
    }
