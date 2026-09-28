"""KMind MCP tools: resolve SiYuan assets, preview changes and coordinate guarded writes."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from siyuan_mcp.core import (
    call_siyuan,
    get_doc_id_by_path,
    get_hpath_by_id,
    mcp,
    resolve_notebook_id,
)
from siyuan_mcp.kmind_backups import (
    _backup_dir,
    _load_backup_view,
    _load_kmind_root,
    list_kmind_backups,
    resolve_diff_reference,
    restore_kmind_backup,
    write_backup,
)
from siyuan_mcp.kmind_storage import _sha256, commit_asset, dump_kmind_bytes, load_kmind
from siyuan_mcp.kmind_tree import (
    _locate_parent,
    _locate_target,
    _outline,
    _outline_markdown,
    _require_root,
    apply_node_style,
    count_nodes,
    diff_kmind_trees,
    make_node,
    node_plain_text,
    node_uid,
    walk_kmind_nodes,
)


DOC_KMIND_ASSET_ATTR = "custom-data-assets-kmind-doctree-doc"


def find_siyuan_data_dir() -> Path:
    configured = os.getenv("SIYUAN_DATA_DIR", "").strip()
    if configured:
        data_dir = Path(configured).expanduser()
        if not data_dir.is_absolute() or not data_dir.is_dir():
            raise ValueError("SIYUAN_DATA_DIR must be an existing absolute data directory.")
        return data_dir.resolve()
    conf = call_siyuan("/api/system/getConf", {})
    system = (conf or {}).get("conf", {}).get("system", {}) if isinstance(conf, dict) else {}
    data_dir = system.get("dataDir") or (
        str(Path(system["workspaceDir"]) / "data") if system.get("workspaceDir") else None
    )
    if not data_dir:
        raise RuntimeError(
            "SiYuan did not expose its local data directory. For local KMind tools, "
            "set SIYUAN_DATA_DIR to this SiYuan workspace's absolute data directory."
        )
    return Path(data_dir)


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
        notebook_id = resolve_notebook_id(notebook)
        resolved_id = get_doc_id_by_path(notebook_id, path)
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
    hpath = get_hpath_by_id(resolved_id)
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

    def make_backup(original_bytes: bytes) -> str | None:
        if not backup:
            return None
        return write_backup(
            data_dir=find_siyuan_data_dir(),
            asset_abs=asset_abs,
            asset_rel=meta["assetRelPath"],
            doc_id=meta["docId"],
            operation=operation,
            sha256_before=sha_before,
            size_bytes=len(original_bytes),
            timestamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
            raw_bytes=original_bytes,
        )

    backup_name = commit_asset(asset_abs, sha_before, new_bytes, _sha256, make_backup)
    base["dryRun"] = False
    base["sha256After"] = _sha256(new_bytes)
    base["sizeBytes"] = len(new_bytes)
    base["backup"] = backup_name
    return base


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
