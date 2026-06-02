"""Generic SiYuan internal-link helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from siyuan_research_mcp.core import call_siyuan, current_default_notebook, mcp

BLOCK_ID_RE = re.compile(r"^\d{14}-[0-9a-z]{7}$")


def validate_block_id(id: str) -> str:
    """Validate and normalize a SiYuan block/document id."""
    clean = id.strip()
    if not BLOCK_ID_RE.match(clean):
        raise ValueError(f"Invalid SiYuan block id: {id!r}")
    return clean


def escape_link_label(label: str) -> str:
    return label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


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


def normalize_doc_path(value: str) -> str:
    clean = re.sub(r"/+", "/", value.strip().replace("\\", "/"))
    if not clean:
        raise ValueError("Document path cannot be empty.")
    return clean if clean.startswith("/") else f"/{clean}"


def format_doc_link(doc: Mapping[str, Any], label: str | None = None) -> dict[str, Any]:
    """Format a resolved document as a canonical SiYuan block link."""
    doc_id = validate_block_id(str(doc.get("id") or ""))
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


def extract_doc_ids(data: Any) -> list[str]:
    """Extract all document ids returned by /api/filetree/getIDsByHPath."""
    raw_ids: list[Any] = []
    if isinstance(data, list):
        raw_ids = data
    elif isinstance(data, dict):
        ids = data.get("ids")
        raw_ids = ids if isinstance(ids, list) else [data.get("id")]

    result: list[str] = []
    for item in raw_ids:
        value = item.get("id") if isinstance(item, dict) else item
        if value:
            result.append(str(value))
    return result


def extract_notebooks(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("notebooks", "boxes"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def find_notebook(id_or_name: str | None) -> dict[str, Any] | None:
    if not id_or_name:
        return None

    data = call_siyuan("/api/notebook/lsNotebooks", {})
    for notebook in extract_notebooks(data):
        if notebook.get("id") == id_or_name or notebook.get("name") == id_or_name:
            return notebook
    return None


def resolve_notebook_id(id_or_name: str | None = None) -> str:
    candidate = id_or_name or current_default_notebook()
    if not candidate:
        raise ValueError("Notebook is required. Provide notebook or set SIYUAN_DEFAULT_NOTEBOOK.")

    notebook = find_notebook(candidate)
    return str(notebook.get("id") if notebook else candidate)


def get_doc_ids_by_path(notebook_id: str, path: str) -> list[str]:
    data = call_siyuan(
        "/api/filetree/getIDsByHPath",
        {
            "notebook": notebook_id,
            "path": normalize_doc_path(path),
        },
    )
    return extract_doc_ids(data)


def get_hpath_by_id(id: str) -> str | None:
    data = call_siyuan("/api/filetree/getHPathByID", {"id": id})
    return str(data) if data else None


def candidate_links(ids: Sequence[str], label: str | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for doc_id in ids:
        hpath = get_hpath_by_id(doc_id) or ""
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
        return {
            "found": False,
            "ambiguous": True,
            "notebook": notebook_id,
            "path": doc_path,
            "label": label.strip() if label and label.strip() else None,
            "candidates": candidate_links(ids, label),
        }

    hpath = get_hpath_by_id(ids[0]) or doc_path
    result = format_doc_link({"id": ids[0], "hpath": hpath}, label)
    result.update({"notebook": notebook_id, "path": doc_path})
    return result
