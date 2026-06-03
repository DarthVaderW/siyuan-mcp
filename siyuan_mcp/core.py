"""Shared core for the SiYuan MCP server.

Holds the single FastMCP instance, runtime configuration, and the low-level
SiYuan HTTP client. Tool modules (server.py, attributeview.py, and future
kmind.py) import from here so they all register on the same `mcp` instance.
This module must never be run as ``__main__``.
"""

from __future__ import annotations

import json
import os
import random
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from siyuan_mcp._version import get_version


VERSION = get_version()
ROOT_DIR = Path(__file__).resolve().parents[1]
SIYUAN_ID_RE = re.compile(r"^\d{14}-[0-9a-z]{7}$")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        os.environ[key] = value


load_dotenv(ROOT_DIR / ".env")

BASE_URL = os.getenv("SIYUAN_BASE_URL", "http://127.0.0.1:6806").rstrip("/")
TOKEN = os.getenv("SIYUAN_TOKEN", "")
DEFAULT_NOTEBOOK = os.getenv("SIYUAN_DEFAULT_NOTEBOOK", "")
ALLOW_RAW_API = os.getenv("SIYUAN_ALLOW_RAW_API", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

mcp = FastMCP("siyuan-mcp")


def current_base_url() -> str:
    return BASE_URL


def current_token() -> str:
    return TOKEN


def current_default_notebook() -> str:
    return DEFAULT_NOTEBOOK


def current_allow_raw_api() -> bool:
    return ALLOW_RAW_API


def assert_api_endpoint(endpoint: str) -> None:
    if not endpoint.startswith("/api/"):
        raise ValueError("Endpoint must start with /api/.")
    if ".." in endpoint:
        raise ValueError("Endpoint cannot contain '..'.")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def call_siyuan(endpoint: str, payload: dict[str, Any] | None = None) -> Any:
    assert_api_endpoint(endpoint)
    base_url = current_base_url()
    token = current_token()
    if not token:
        raise RuntimeError("SIYUAN_TOKEN is not configured.")

    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        base_url + endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {token}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SiYuan HTTP {error.code} for {endpoint}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cannot reach SiYuan at {base_url}: {error.reason}") from error

    try:
        decoded = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return text

    if isinstance(decoded, dict) and isinstance(decoded.get("code"), int) and decoded["code"] != 0:
        raise RuntimeError(
            f"SiYuan API error {decoded['code']} for {endpoint}: "
            f"{decoded.get('msg') or stable_json(decoded)}"
        )

    if isinstance(decoded, dict) and "data" in decoded:
        return decoded["data"]
    return decoded


def looks_like_siyuan_id(value: str) -> bool:
    return bool(SIYUAN_ID_RE.match(value.strip()))


def normalize_doc_path(value: str) -> str:
    clean = re.sub(r"/+", "/", value.strip().replace("\\", "/"))
    if not clean:
        raise ValueError("Document path cannot be empty.")
    return clean if clean.startswith("/") else f"/{clean}"


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


def get_doc_ids_by_path(notebook_id: str, path: str) -> list[str]:
    data = call_siyuan(
        "/api/filetree/getIDsByHPath",
        {
            "notebook": notebook_id,
            "path": normalize_doc_path(path),
        },
    )
    return extract_doc_ids(data)


def get_doc_id_by_path(notebook_id: str, path: str) -> str | None:
    ids = get_doc_ids_by_path(notebook_id, path)
    return ids[0] if ids else None


def get_hpath_by_id(id: str) -> str | None:
    data = call_siyuan("/api/filetree/getHPathByID", {"id": id})
    return str(data) if data else None


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

    candidate = candidate.strip()
    if looks_like_siyuan_id(candidate):
        return candidate

    notebook = find_notebook(candidate)
    return str(notebook.get("id") if notebook else candidate)


def generate_node_id() -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    suffix = "".join(random.choice(alphabet) for _ in range(7))
    return datetime.now().strftime("%Y%m%d%H%M%S") + "-" + suffix
