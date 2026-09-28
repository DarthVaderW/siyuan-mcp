"""STDIO entry point, runtime configuration, and explicit tool registration."""

from __future__ import annotations

from typing import Any

from siyuan_mcp import core
from siyuan_mcp.core import mcp


@mcp.resource("siyuan://config")
def siyuan_config() -> str:
    """Runtime configuration without secrets."""
    token = core.current_token()
    return core.stable_json(
        {
            "name": "siyuan-mcp",
            "version": core.VERSION,
            "baseUrl": core.current_base_url(),
            "defaultNotebook": core.current_default_notebook() or None,
            "tokenConfigured": bool(token),
            "rawApiEnabled": core.current_allow_raw_api(),
            "implementation": "python",
        }
    )


@mcp.tool()
def siyuan_call_api(endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a raw SiYuan /api endpoint. Disabled by default."""
    if not core.current_allow_raw_api():
        raise PermissionError("Raw API access is disabled. Set SIYUAN_ALLOW_RAW_API=true to enable it.")
    core.assert_api_endpoint(endpoint)
    data = core.call_siyuan(endpoint, payload or {})
    return {"endpoint": endpoint, "result": data}


# Each module registers its tools on the shared MCP instance.
from siyuan_mcp import notebooks as notebooks  # noqa: E402,F401
from siyuan_mcp import documents as documents  # noqa: E402,F401
from siyuan_mcp import blocks as blocks  # noqa: E402,F401
from siyuan_mcp import search as search  # noqa: E402,F401
from siyuan_mcp import attributeview as attributeview  # noqa: E402,F401
from siyuan_mcp import attributeview_rows as attributeview_rows  # noqa: E402,F401
from siyuan_mcp import attributeview_views as attributeview_views  # noqa: E402,F401
from siyuan_mcp import kmind as kmind  # noqa: E402,F401
from siyuan_mcp import links as links  # noqa: E402,F401


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
