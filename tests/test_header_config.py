from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from siyuan_research_mcp import server


@contextmanager
def headers(values: dict[str, str]) -> Iterator[None]:
    original = server.request_headers
    server.request_headers = lambda: values  # type: ignore[assignment]
    try:
        yield
    finally:
        server.request_headers = original  # type: ignore[assignment]


def main() -> None:
    with headers({"authorization": "Bearer siyuan-secret"}):
        assert server.current_token() == "siyuan-secret"

    with headers(
        {
            "x-siyuan-token": "header-token",
            "x-siyuan-base-url": "http://127.0.0.1:6806/",
            "x-siyuan-default-notebook": "Papers",
            "x-siyuan-codex-notebook": "CodeX",
            "x-siyuan-allow-raw-api": "true",
        }
    ):
        assert server.current_token() == "header-token"
        assert server.current_base_url() == "http://127.0.0.1:6806"
        assert server.current_default_notebook() == "Papers"
        assert server.current_codex_notebook() == "CodeX"
        assert server.current_allow_raw_api() is True


if __name__ == "__main__":
    main()
