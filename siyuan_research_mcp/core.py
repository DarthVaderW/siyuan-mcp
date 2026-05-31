"""Shared core for the SiYuan MCP server.

Holds the single FastMCP instance, runtime configuration, header/config
resolution, and the low-level SiYuan HTTP client. Tool modules (server.py,
attributeview.py, and future kmind.py) import from here so they all register
on the same `mcp` instance. This module must never be run as ``__main__``.
"""

from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

VERSION = "0.1.7"
ROOT_DIR = Path(__file__).resolve().parents[1]


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
CODEX_NOTEBOOK = os.getenv("SIYUAN_CODEX_NOTEBOOK", "20260222005018-okt4cvb")
ALLOW_RAW_API = os.getenv("SIYUAN_ALLOW_RAW_API", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MCP_HOST = os.getenv("SIYUAN_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("SIYUAN_MCP_PORT", "6816"))
MCP_PATH = os.getenv("SIYUAN_MCP_PATH", "/mcp")

mcp = FastMCP("siyuan-mcp", host=MCP_HOST, port=MCP_PORT, streamable_http_path=MCP_PATH)


def request_headers() -> Any:
    try:
        request = mcp.get_context().request_context.request
    except Exception:
        return {}
    return getattr(request, "headers", {}) or {}


def header_value(*names: str) -> str | None:
    headers = request_headers()
    for name in names:
        try:
            value = headers.get(name)
        except AttributeError:
            value = None
        if value:
            return str(value).strip()
    return None


def bearer_token() -> str | None:
    authorization = header_value("authorization")
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() in {"bearer", "token"} and value.strip():
        return value.strip()
    return None


def env_or_header(env_value: str, *headers: str) -> str:
    return header_value(*headers) or env_value


def truthy_header(env_value: bool, *headers: str) -> bool:
    value = header_value(*headers)
    if value is None:
        return env_value
    return value.lower() in {"1", "true", "yes", "on"}


def current_base_url() -> str:
    return env_or_header(
        BASE_URL,
        "x-siyuan-base-url",
        "siyuan-base-url",
    ).rstrip("/")


def current_token() -> str:
    return (
        header_value("x-siyuan-token", "siyuan-token")
        or bearer_token()
        or TOKEN
    )


def current_default_notebook() -> str:
    return env_or_header(
        DEFAULT_NOTEBOOK,
        "x-siyuan-default-notebook",
        "siyuan-default-notebook",
    )


def current_codex_notebook() -> str:
    return env_or_header(
        CODEX_NOTEBOOK,
        "x-siyuan-codex-notebook",
        "siyuan-codex-notebook",
    )


def current_allow_raw_api() -> bool:
    return truthy_header(
        ALLOW_RAW_API,
        "x-siyuan-allow-raw-api",
        "siyuan-allow-raw-api",
    )


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


def generate_node_id() -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    suffix = "".join(random.choice(alphabet) for _ in range(7))
    return datetime.now().strftime("%Y%m%d%H%M%S") + "-" + suffix
