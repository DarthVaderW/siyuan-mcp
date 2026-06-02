"""Generic SiYuan internal-link helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from siyuan_mcp import core

mcp = core.mcp
BLOCK_ID_RE = core.SIYUAN_ID_RE
MAX_CANDIDATE_LINKS = 10
normalize_doc_path = core.normalize_doc_path
extract_doc_ids = core.extract_doc_ids
resolve_notebook_id = core.resolve_notebook_id
get_doc_ids_by_path = core.get_doc_ids_by_path


def validate_block_id(id: str) -> str:
    """Validate and normalize a SiYuan block/document id."""
    clean = id.strip()
    if not BLOCK_ID_RE.match(clean):
        raise ValueError(f"Invalid SiYuan block id: {id!r}")
    return clean


def escape_link_label(label: str) -> str:
    clean = label.replace("\r", " ").replace("\n", " ")
    return clean.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def format_block_link(id: str, label: str) -> dict[str, str]:
    """Return a canonical Markdown link to a SiYuan block/document id."""
    clean_id = validate_block_id(id)
    clean_label = label.strip()
    if not clean_label:
        raise ValueError("Link label is required.")

    url = f"siyuan://blocks/{clean_id}"
    return {
        "id": clean_id,
        "label": clean_label,
        "url": url,
        "markdown": f"[{escape_link_label(clean_label)}]({url})",
    }


def derive_label_from_hpath(hpath: str) -> str:
    clean = re.sub(r"/+", "/", hpath.strip())
    clean = clean.rstrip("/")
    if not clean or clean == "/":
        return "SiYuan document"
    return clean.rsplit("/", 1)[-1] or "SiYuan document"


def format_doc_link(doc: Mapping[str, Any], label: str | None = None) -> dict[str, Any]:
    """Format a resolved document as a canonical SiYuan block link."""
    if not doc.get("id"):
        raise ValueError("Document is missing 'id' field.")
    doc_id = validate_block_id(str(doc["id"]))
    hpath = str(doc.get("hpath") or doc.get("path") or "")
    clean_label = label.strip() if label and label.strip() else derive_label_from_hpath(hpath)
    link = format_block_link(doc_id, clean_label)
    return {
        "found": True,
        "ambiguous": False,
        "id": link["id"],
        "hpath": hpath or None,
        "label": link["label"],
        "url": link["url"],
        "markdown": link["markdown"],
    }


def candidate_links(
    ids: Sequence[str],
    label: str | None = None,
    *,
    limit: int = MAX_CANDIDATE_LINKS,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for doc_id in ids[:limit]:
        hpath = core.get_hpath_by_id(doc_id) or ""
        candidates.append(format_doc_link({"id": doc_id, "hpath": hpath}, label))
    return candidates


@mcp.tool()
def siyuan_make_block_link(id: str, label: str) -> dict[str, str]:
    """Create a canonical Markdown link for a SiYuan block/document id."""
    return format_block_link(id, label)


@mcp.tool()
def siyuan_make_doc_link(
    path: str,
    label: str | None = None,
    notebook: str | None = None,
) -> dict[str, Any]:
    """Resolve a document path and create a canonical SiYuan document link."""
    notebook_id = resolve_notebook_id(notebook)
    doc_path = normalize_doc_path(path)
    ids = get_doc_ids_by_path(notebook_id, doc_path)

    if not ids:
        fallback_label = label.strip() if label and label.strip() else derive_label_from_hpath(doc_path)
        return {
            "found": False,
            "ambiguous": False,
            "notebook": notebook_id,
            "path": doc_path,
            "label": fallback_label,
            "candidates": [],
        }

    if len(ids) > 1:
        fallback_label = label.strip() if label and label.strip() else derive_label_from_hpath(doc_path)
        candidates = candidate_links(ids, label)
        return {
            "found": False,
            "ambiguous": True,
            "notebook": notebook_id,
            "path": doc_path,
            "label": fallback_label,
            "candidateCount": len(ids),
            "returnedCandidateCount": len(candidates),
            "candidatesTruncated": len(ids) > len(candidates),
            "candidates": candidates,
        }

    hpath = core.get_hpath_by_id(ids[0]) or doc_path
    result = format_doc_link({"id": ids[0], "hpath": hpath}, label)
    result.update({"notebook": notebook_id, "path": doc_path})
    return result
