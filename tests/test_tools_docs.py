"""Consistency test: registered MCP tools == docs/TOOLS.md documented tools.

Offline only. Importing siyuan_mcp.server registers every tool (server.py's
own tools plus attributeview.py/kmind.py/links.py, imported for their side
effect) on the shared FastMCP instance without touching the network or
requiring SIYUAN_TOKEN -- SiYuan is only contacted when a tool is actually
called, never at import/registration time. See docs/REPAIR_PLAN_2026-07-10.md
P1.3.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from siyuan_mcp import server as S

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DOC = ROOT / "docs" / "TOOLS.md"

# docs/TOOLS.md documents each tool under its own level-3 heading, e.g.:
#   ### `siyuan_ping`
TOOL_HEADING_RE = re.compile(r"^### `([A-Za-z0-9_]+)`\s*$", re.MULTILINE)


def registered_tool_names() -> set[str]:
    tools = asyncio.run(S.mcp.list_tools())
    return {tool.name for tool in tools}


def documented_tool_names() -> set[str]:
    text = TOOLS_DOC.read_text(encoding="utf-8")
    return set(TOOL_HEADING_RE.findall(text))


def test_tools_doc_exists_and_is_non_trivial() -> None:
    assert TOOLS_DOC.is_file(), f"missing {TOOLS_DOC}"
    documented = documented_tool_names()
    assert len(documented) > 50, f"suspiciously few tools parsed from TOOLS.md: {len(documented)}"


def test_registered_tools_match_documented_tools() -> None:
    registered = registered_tool_names()
    documented = documented_tool_names()

    missing_from_docs = sorted(registered - documented)
    stale_in_docs = sorted(documented - registered)

    assert not missing_from_docs, (
        f"tools registered but not documented in {TOOLS_DOC.relative_to(ROOT)}: {missing_from_docs}"
    )
    assert not stale_in_docs, (
        f"tools documented in {TOOLS_DOC.relative_to(ROOT)} but no longer registered: {stale_in_docs}"
    )


def test_every_documented_heading_is_a_unique_tool_name() -> None:
    text = TOOLS_DOC.read_text(encoding="utf-8")
    headings = TOOL_HEADING_RE.findall(text)
    duplicates = sorted({name for name in headings if headings.count(name) > 1})
    assert not duplicates, f"duplicate tool headings in {TOOLS_DOC.relative_to(ROOT)}: {duplicates}"


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
