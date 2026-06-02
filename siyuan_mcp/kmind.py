"""SiYuan KMind (mind-map) tools.

KMind data is not an independent service: a KMind page is a SiYuan ``.sy``
document whose ``custom-data-assets-kmind-doctree-doc`` property points at a
JSON ``.kmind`` file under ``<dataDir>/assets``. These tools provide low-level,
safe primitives over that JSON (read/export/search/add/style) with optimistic
concurrency (sha256) and automatic backups for writes.

Workflow decisions belong in callers, not here.
Importing this module registers the ``siyuan_kmind_*`` tools on the shared
``mcp`` instance from :mod:`siyuan_mcp.core`.
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

from siyuan_mcp.core import call_siyuan, current_default_notebook, mcp

# --- Constants ---------------------------------------------------------------

DOC_KMIND_ASSET_ATTR = "custom-data-assets-kmind-doctree-doc"
BACKUP_REL_DIR = ("storage", "siyuan-mcp-kmind-backups")
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

# Node fields that carry content/meaning (vs. styling or pure view state). Used
# by siyuan_kmind_diff to bucket changed fields; any changed field that is not a
# node-style, branch-line, or content field falls into the "other" bucket.
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
    data_root = data_dir.resolve()
    asset_abs = (data_dir / asset_rel).resolve()
    # Path-traversal guard: the asset must stay inside the data dir and be .kmind.
    try:
        asset_abs.relative_to(data_root)
    except ValueError as exc:
        raise ValueError("Resolved KMind asset escapes the SiYuan data directory.") from exc
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


def _load_backup_view(data_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    backup_dir = _backup_dir(data_dir)
    for entry in _load_backup_index(backup_dir):
        decorated = dict(entry)
        decorated["_backupStore"] = "current"
        decorated["_backupDir"] = str(backup_dir)
        entries.append(decorated)
    return entries


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
    if (backup_dir / backup_name).exists():
        suffix = "".join(random.choice("0123456789abcdef") for _ in range(6))
        backup_name = f"{timestamp}__{doc_id}__before-{operation}-{suffix}.kmind"
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


def _backup_path_in_dir(backup_dir: Path, backup_path: str | None) -> Path | None:
    """Resolve a backup path only if it stays inside the backup directory."""
    if not backup_path:
        return None
    base = backup_dir.resolve()
    candidate = (backup_dir / str(backup_path)).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def _entry_backup_dir(default_backup_dir: Path, entry: dict[str, Any]) -> Path:
    backup_dir = entry.get("_backupDir")
    return Path(str(backup_dir)) if backup_dir else default_backup_dir


def _entry_backup_path(default_backup_dir: Path, entry: dict[str, Any]) -> Path | None:
    return _backup_path_in_dir(_entry_backup_dir(default_backup_dir, entry), entry.get("backupPath"))


def _candidate_backup_dirs(default_backup_dir: Path, index: list[dict[str, Any]]) -> list[Path]:
    dirs = [default_backup_dir]
    for entry in index:
        backup_dir = _entry_backup_dir(default_backup_dir, entry)
        if backup_dir not in dirs:
            dirs.append(backup_dir)
    return dirs


def _newest_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not entries:
        return None
    return max(entries, key=lambda e: (e.get("createdAt", ""), e.get("_backupStore", ""), e.get("backupPath", "")))


def list_kmind_backups(backup_dir: Path, index: list[dict[str, Any]], doc_id: str) -> dict[str, Any]:
    """Summarize the backups recorded for one document, newest first (read-only).

    Pure: operates on a given backup dir + index, so it needs no live SiYuan.
    Each backup reports backupPath / createdAt / operation / sha256Before /
    sizeBytes / source / existsOnDisk. The summary reports count, totalSizeBytes
    (sum of recorded sizeBytes across listed backups), missingFiles (entries whose
    file is gone from disk), and backupDir. A document with no backups yields an
    empty list and a zeroed summary — never an error.
    """
    backups: list[dict[str, Any]] = []
    missing_files = 0
    total_size = 0
    for entry in index:
        if entry.get("docId") != doc_id:
            continue
        backup_path = entry.get("backupPath")
        entry_backup_dir = _entry_backup_dir(backup_dir, entry)
        backup_abs = _entry_backup_path(backup_dir, entry)
        exists = backup_abs is not None and backup_abs.exists()
        if not exists:
            missing_files += 1
        total_size += int(entry.get("sizeBytes") or 0)
        backups.append(
            {
                "backupPath": backup_path,
                "createdAt": entry.get("createdAt"),
                "operation": entry.get("operation"),
                "sha256Before": entry.get("sha256Before"),
                "sizeBytes": entry.get("sizeBytes"),
                "source": entry.get("source"),
                "backupStore": entry.get("_backupStore") or "current",
                "backupDir": str(entry_backup_dir),
                "existsOnDisk": exists,
            }
        )
    backups.sort(key=lambda e: (e.get("createdAt") or "", e.get("backupPath") or ""), reverse=True)
    return {
        "backups": backups,
        "summary": {
            "count": len(backups),
            "totalSizeBytes": total_size,
            "missingFiles": missing_files,
            "backupDir": str(backup_dir),
            "backupStores": sorted({str(e.get("backupStore")) for e in backups}),
        },
    }


# --- Diff (read-only, style-aware) -------------------------------------------


def classify_kmind_field(field: str) -> str:
    """Bucket a node-data field name: content / nodeStyle / branchLine / other."""
    if field in LINE_STYLE_FIELDS:
        return "branchLine"
    if field in SAFE_NODE_STYLE_FIELDS:
        return "nodeStyle"
    if field in CONTENT_FIELDS:
        return "content"
    return "other"


def _load_kmind_root(asset_abs: str | Path) -> tuple[dict[str, Any], str, int]:
    data, sha256, size_bytes = load_kmind(asset_abs)
    return _require_root(data), sha256, size_bytes


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


def _latest_backup_entry(index: list[dict[str, Any]], doc_id: str) -> dict[str, Any] | None:
    entries = [e for e in index if e.get("docId") == doc_id and e.get("backupPath")]
    if not entries:
        return None
    return max(entries, key=lambda e: e.get("createdAt", ""))


def _backup_reference_report(
    kind: str, entry: dict[str, Any] | None, ref_abs: Path, sha256: str, size_bytes: int
) -> dict[str, Any]:
    entry = entry or {}
    return {
        "kind": kind,
        "backupPath": entry.get("backupPath") or ref_abs.name,
        "createdAt": entry.get("createdAt"),
        "operation": entry.get("operation"),
        "sha256Before": entry.get("sha256Before"),
        "sha256": sha256,  # actual content sha of the reference we loaded
        "sizeBytes": size_bytes,
        "backupStore": entry.get("_backupStore"),
        "backupDir": entry.get("_backupDir") or str(ref_abs.parent),
    }


def resolve_diff_reference(
    backup_dir: Path,
    index: list[dict[str, Any]],
    doc_id: str,
    against_backup_path: str | None = None,
    against_sha256: str | None = None,
    against_file: str | None = None,
) -> dict[str, Any]:
    """Resolve the reference KMind tree for a diff (read-only).

    Precedence: at most one explicit reference (against_file / against_backup_path
    / against_sha256), else the latest backup for ``doc_id``. Returns
    ``{"status": "ok", "root": <root>, "reference": {...}}`` or, when nothing is
    available, ``{"status": "no-reference-available", "root": None,
    "reference": None, "message": ...}`` — it never silently diffs against
    nothing. The reference report always names the selected source.
    """
    explicit = [x for x in (against_backup_path, against_sha256, against_file) if x]
    if len(explicit) > 1:
        raise ValueError(
            "Provide at most one explicit reference: against_backup_path, "
            "against_sha256, or against_file."
        )

    if against_file:
        ref_abs = Path(against_file)
        if not ref_abs.exists():
            raise FileNotFoundError(f"Reference .kmind file not found: {against_file}")
        root, sha256, size_bytes = _load_kmind_root(ref_abs)
        return {
            "status": "ok",
            "root": root,
            "reference": {
                "kind": "file",
                "filePath": str(ref_abs),
                "sha256": sha256,
                "sizeBytes": size_bytes,
            },
        }

    if against_backup_path:
        name = Path(against_backup_path).name
        entry = _newest_entry([e for e in index if e.get("backupPath") == name])
        if entry:
            ref_abs = _entry_backup_path(backup_dir, entry)
            if ref_abs is None:
                raise ValueError(f"Backup path escapes backup dir: {against_backup_path}")
        else:
            ref_abs = next(
                ((candidate / name) for candidate in _candidate_backup_dirs(backup_dir, index) if (candidate / name).exists()),
                None,
            )
        if ref_abs is None or not ref_abs.exists():
            raise FileNotFoundError(f"Backup not found in backup stores: {against_backup_path}")
        root, sha256, size_bytes = _load_kmind_root(ref_abs)
        return {
            "status": "ok",
            "root": root,
            "reference": _backup_reference_report("backup-path", entry, ref_abs, sha256, size_bytes),
        }

    if against_sha256:
        entry = next(
            (e for e in index if e.get("sha256Before") == against_sha256 and e.get("docId") == doc_id),
            None,
        )
        if not entry:
            raise ValueError(f"No backup with sha256Before={against_sha256} for document {doc_id}.")
        ref_abs = _entry_backup_path(backup_dir, entry)
        if ref_abs is None:
            raise ValueError(f"Backup path escapes backup dir: {entry.get('backupPath')}")
        if not ref_abs.exists():
            raise FileNotFoundError(f"Backup file missing on disk: {entry['backupPath']}")
        root, sha256, size_bytes = _load_kmind_root(ref_abs)
        return {
            "status": "ok",
            "root": root,
            "reference": _backup_reference_report("sha256", entry, ref_abs, sha256, size_bytes),
        }

    entry = _latest_backup_entry(index, doc_id)
    if not entry:
        return {
            "status": "no-reference-available",
            "root": None,
            "reference": None,
            "message": (
                "No backup found for this document. Pass against_backup_path, "
                "against_sha256, or against_file to diff against an explicit reference."
            ),
        }
    ref_abs = _entry_backup_path(backup_dir, entry)
    if ref_abs is None:
        return {
            "status": "no-reference-available",
            "root": None,
            "reference": None,
            "message": f"Latest backup path escapes backup dir: {entry.get('backupPath')}.",
        }
    if not ref_abs.exists():
        return {
            "status": "no-reference-available",
            "root": None,
            "reference": None,
            "message": f"Latest backup file is missing on disk: {entry['backupPath']}.",
        }
    root, sha256, size_bytes = _load_kmind_root(ref_abs)
    return {
        "status": "ok",
        "root": root,
        "reference": _backup_reference_report("latest-backup", entry, ref_abs, sha256, size_bytes),
    }


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
            timestamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
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


# --- Restore (write, dry-run-first) ------------------------------------------


def resolve_restore_source(
    backup_dir: Path,
    index: list[dict[str, Any]],
    doc_id: str,
    backup_path: str | None = None,
    sha256_before: str | None = None,
) -> dict[str, Any]:
    """Resolve which backup to restore for ``doc_id`` (read-only resolution).

    Requires exactly one explicit identity — ``backup_path`` or ``sha256_before``;
    there is deliberately no "latest" default for a restore. The chosen backup
    MUST be recorded in the index for THIS document (its ``docId`` must match) and
    its file must stay inside the backup dir. Returns the loaded backup (raw bytes
    + validated root + sha) and its index entry. Raises ValueError /
    FileNotFoundError on any mismatch. No SiYuan calls.
    """
    provided = [x for x in (backup_path, sha256_before) if x]
    if len(provided) != 1:
        raise ValueError(
            "Provide exactly one backup identity: backup_path or sha256_before "
            "(restore has no 'latest' default)."
        )

    if backup_path:
        name = Path(backup_path).name
        entry = _newest_entry([e for e in index if e.get("backupPath") == name])
        if not entry:
            raise ValueError(f"No backup named {name!r} recorded in the index.")
    else:
        entry = _newest_entry(
            [e for e in index if e.get("sha256Before") == sha256_before and e.get("docId") == doc_id]
        )
        if not entry:
            raise ValueError(
                f"No backup with sha256Before={sha256_before} recorded for document {doc_id}."
            )

    if entry.get("docId") != doc_id:
        raise ValueError(
            f"Refusing to restore: backup belongs to document {entry.get('docId')!r}, "
            f"not {doc_id!r}."
        )

    backup_abs = _entry_backup_path(backup_dir, entry)
    if backup_abs is None:
        raise ValueError(f"Backup path escapes backup dir: {entry.get('backupPath')!r}.")
    if not backup_abs.exists():
        raise FileNotFoundError(f"Backup file missing on disk: {entry.get('backupPath')!r}.")

    raw = backup_abs.read_bytes()
    backup_sha256 = _sha256(raw)
    recorded_sha256 = entry.get("sha256Before")
    if recorded_sha256 and recorded_sha256 != backup_sha256:
        raise ValueError(
            f"Backup content hash mismatch for {entry.get('backupPath')!r}: "
            f"index records {recorded_sha256}, file is {backup_sha256}."
        )
    root = _require_root(json.loads(raw.decode("utf-8")))  # validate restorable JSON + root
    return {
        "backupAbs": backup_abs,
        "backupRaw": raw,
        "backupRoot": root,
        "backupSha256": backup_sha256,
        "backupSizeBytes": len(raw),
        "entry": {
            "backupPath": entry.get("backupPath"),
            "createdAt": entry.get("createdAt"),
            "operation": entry.get("operation"),
            "sha256Before": entry.get("sha256Before"),
            "sizeBytes": entry.get("sizeBytes"),
            "source": entry.get("source"),
            "docId": entry.get("docId"),
            "backupStore": entry.get("_backupStore") or "current",
            "backupDir": str(_entry_backup_dir(backup_dir, entry)),
        },
    }


def restore_kmind_backup(
    *,
    asset_abs: Path,
    data_dir: Path,
    asset_rel: str,
    doc_id: str,
    index: list[dict[str, Any]],
    backup_path: str | None = None,
    sha256_before: str | None = None,
    expected_sha256: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Restore a KMind asset from one of its own backups, byte-for-byte.

    Offline-friendly: the caller does SiYuan resolution and passes paths + the
    backup index, so this needs no live SiYuan. ``dry_run`` (default True) writes
    nothing and creates no backup — it returns the chosen backup, current/backup
    sha, and a best-effort diff summary (current -> backup) so the change can be
    reviewed first. A real restore re-checks the on-disk sha to avoid clobbering a
    concurrent KMind UI edit, creates a ``before-restore`` backup of the current
    file, then writes the backup bytes back verbatim.
    """
    backup_dir = _backup_dir(data_dir)
    src = resolve_restore_source(backup_dir, index, doc_id, backup_path, sha256_before)

    if not asset_abs.exists():
        raise FileNotFoundError(f"KMind asset not found on disk: {asset_abs}")
    cur_raw = asset_abs.read_bytes()
    cur_sha = _sha256(cur_raw)
    if expected_sha256 and expected_sha256 != cur_sha:
        raise ValueError(
            f"sha256 mismatch for {doc_id}: expected {expected_sha256}, on-disk "
            f"{cur_sha}. Re-read the KMind file before restoring."
        )

    # Best-effort preview of what restoring would change (current -> backup).
    diff_summary: dict[str, Any] | None = None
    try:
        cur_root = _require_root(json.loads(cur_raw.decode("utf-8")))
        diff_summary = diff_kmind_trees(cur_root, src["backupRoot"])["summary"]
    except (json.JSONDecodeError, ValueError):
        diff_summary = None

    result: dict[str, Any] = {
        "operation": "restore",
        "backup": {**src["entry"], "backupSha256": src["backupSha256"]},
        "current": {"sha256": cur_sha, "sizeBytes": len(cur_raw)},
        "willRestoreToSha256": src["backupSha256"],
        "identical": src["backupSha256"] == cur_sha,
        "diffSummary": diff_summary,
    }

    if dry_run:
        result["dryRun"] = True
        result["backupCreated"] = None
        result["hint"] = (
            "Preview only — nothing written. For full per-node detail run "
            "siyuan_kmind_diff against this backup, then re-call with dry_run=false "
            "to apply."
        )
        return result

    # Re-read just before writing to catch a concurrent UI edit during processing.
    if _sha256(asset_abs.read_bytes()) != cur_sha:
        raise ValueError(
            "KMind file changed on disk during processing; aborting restore to "
            "avoid overwriting a concurrent edit. Re-read and retry."
        )

    backup_created = write_backup(
        data_dir=data_dir,
        asset_abs=asset_abs,
        asset_rel=asset_rel,
        doc_id=doc_id,
        operation="restore",
        sha256_before=cur_sha,
        size_bytes=len(cur_raw),
        timestamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
    )
    asset_abs.write_bytes(src["backupRaw"])
    new_raw = asset_abs.read_bytes()
    result["dryRun"] = False
    result["backupCreated"] = backup_created
    result["sha256After"] = _sha256(new_raw)
    result["sizeBytesAfter"] = len(new_raw)
    return result


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


@mcp.tool()
def siyuan_kmind_diff(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
    against_backup_path: str | None = None,
    against_sha256: str | None = None,
    against_file: str | None = None,
) -> dict[str, Any]:
    """Diff a KMind file against a reference version (read-only; no write, no backup).

    The reference defaults to the latest backup of this document, and the result
    always reports which reference was selected (backupPath / createdAt /
    sha256Before). Pass at most one explicit reference instead:
    against_backup_path (a backup file name), against_sha256 (matches a backup's
    sha256Before), or against_file (another .kmind file). If no reference exists,
    returns status="no-reference-available" instead of silently diffing against
    nothing.

    Nodes are paired by uid. Returns added / removed / changed; each changed node
    lists its changed fields bucketed into content / nodeStyle /
    branchLine (lineColor, lineWidth) / other, with before/after values.
    """
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)
    asset_abs = Path(meta["assetAbsPath"])
    if not meta["exists"] or not asset_abs.exists():
        raise FileNotFoundError(f"KMind asset not found on disk: {asset_abs}")
    cur_root, cur_sha256, cur_size = _load_kmind_root(asset_abs)

    data_dir = find_siyuan_data_dir()
    backup_dir = _backup_dir(data_dir)
    index = _load_backup_view(data_dir)
    ref = resolve_diff_reference(
        backup_dir,
        index,
        meta["docId"],
        against_backup_path=against_backup_path,
        against_sha256=against_sha256,
        against_file=against_file,
    )

    result: dict[str, Any] = {
        "docId": meta["docId"],
        "title": meta["title"],
        "status": ref["status"],
        "current": {"sha256": cur_sha256, "sizeBytes": cur_size},
        "reference": ref["reference"],
    }
    if ref["status"] != "ok":
        result["message"] = ref.get("message")
        return result

    result["identical"] = (ref["reference"] or {}).get("sha256") == cur_sha256
    result.update(diff_kmind_trees(ref["root"], cur_root))
    return result


@mcp.tool()
def siyuan_kmind_list_backups(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """List the KMind backups recorded for a document, newest first (read-only).

    Locate the document by doc_id (preferred) or path/notebook. Reads the current
    backup index, then returns every backup for this document with backupPath /
    createdAt / operation /
    sha256Before / sizeBytes / source / backupStore / backupDir / existsOnDisk,
    plus a summary. No write, no backup. If the document has no backups, returns
    an empty list with a zeroed summary, not an error.
    """
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)
    data_dir = find_siyuan_data_dir()
    backup_dir = _backup_dir(data_dir)
    index = _load_backup_view(data_dir)
    return {
        "docId": meta["docId"],
        "title": meta["title"],
        "assetRelPath": meta["assetRelPath"],
        **list_kmind_backups(backup_dir, index, meta["docId"]),
    }


@mcp.tool()
def siyuan_kmind_restore_backup(
    path: str | None = None,
    notebook: str | None = None,
    doc_id: str | None = None,
    backup_path: str | None = None,
    sha256_before: str | None = None,
    dry_run: bool = True,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Restore a KMind document from one of its own backups (write; dry-run-first).

    **Defaults to dry_run=True** — a dry run writes nothing and creates no backup;
    it returns the chosen backup, the current and backup sha256, and a best-effort
    diff summary (current -> backup) so you can review the change first (use
    siyuan_kmind_diff for full per-node detail).

    You MUST identify the backup explicitly — there is no "latest" default. Pass
    exactly one of backup_path (a backup file name) or sha256_before (matches a
    backup's recorded sha256Before). The backup must be recorded in the index for
    THIS document; restoring another document's backup is refused.

    With dry_run=false the tool re-checks the on-disk sha (pass expected_sha256 to
    guard against a concurrent KMind UI edit), creates a `before-restore` backup of
    the current file, then writes the backup's bytes back verbatim. Returns the
    old/new sha256 and the name of the before-restore backup created.

    This is the only write tool in the safety layer; it does not move, delete,
    import, or bulk-edit nodes.
    """
    meta = resolve_kmind_doc(path=path, notebook=notebook, doc_id=doc_id)
    asset_abs = Path(meta["assetAbsPath"])
    if not meta["exists"] or not asset_abs.exists():
        raise FileNotFoundError(f"KMind asset not found on disk: {asset_abs}")
    data_dir = find_siyuan_data_dir()
    index = _load_backup_view(data_dir)
    result = restore_kmind_backup(
        asset_abs=asset_abs,
        data_dir=data_dir,
        asset_rel=meta["assetRelPath"],
        doc_id=meta["docId"],
        index=index,
        backup_path=backup_path,
        sha256_before=sha256_before,
        expected_sha256=expected_sha256,
        dry_run=dry_run,
    )
    return {"docId": meta["docId"], "title": meta["title"], **result}
