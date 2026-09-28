"""Read-only block queries and document attribute searches."""

from __future__ import annotations

import re
from typing import Any

from siyuan_mcp import core
from siyuan_mcp.core import mcp


@mcp.tool()
def siyuan_find_docs_by_attrs(
    attrs: dict[str, Any],
    notebook: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find document blocks whose IAL contains all provided attributes."""
    if not attrs:
        raise ValueError("attrs cannot be empty.")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")

    filters = ["type = 'd'"]
    if notebook:
        filters.append("box = " + core.sql_string(core.resolve_notebook_id(notebook)))

    for key, value in attrs.items():
        assert_attr_key(key)
        if value is None:
            filters.append("ial LIKE " + core.sql_string(f"%{key}=%"))
        else:
            filters.append("ial LIKE " + core.sql_string(f"%{key}=\"{str(value)}\"%"))

    stmt = " ".join(
        [
            "SELECT id, box, path, hpath, content, ial, updated",
            "FROM blocks",
            "WHERE " + " AND ".join(filters),
            "ORDER BY updated DESC",
            "LIMIT " + str(int(limit)),
        ]
    )
    rows = core.call_siyuan("/api/query/sql", {"stmt": stmt})
    return {"rows": rows, "stmt": stmt}

@mcp.tool()
def siyuan_sql_query(stmt: str, limit: int = 100) -> dict[str, Any]:
    """Run a read-only SQL query against SiYuan's block database."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    assert_read_only_sql(stmt)
    data = core.call_siyuan("/api/query/sql", {"stmt": stmt})
    if isinstance(data, list):
        return {"rows": data[:limit], "truncated": len(data) > limit}
    return {"rows": data, "truncated": False}

@mcp.tool()
def siyuan_search_blocks(
    keyword: str,
    notebook: str | None = None,
    type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search blocks by text using SiYuan SQL."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    filters = [f"content LIKE {core.sql_string('%' + keyword + '%')}"]
    if notebook:
        filters.append(f"box = {core.sql_string(core.resolve_notebook_id(notebook))}")
    if type:
        filters.append(f"type = {core.sql_string(type)}")

    stmt = " ".join(
        [
            "SELECT id, box, path, hpath, name, alias, memo, tag, type, subtype, content, updated",
            "FROM blocks",
            "WHERE " + " AND ".join(filters),
            "ORDER BY updated DESC",
            "LIMIT " + str(int(limit)),
        ]
    )
    rows = core.call_siyuan("/api/query/sql", {"stmt": stmt})
    return {"rows": rows}

def assert_attr_key(key: str) -> None:
    if not re.match(r"^[A-Za-z0-9_-]+$", key):
        raise ValueError(f"Invalid attribute key: {key}")

def assert_read_only_sql(stmt: str) -> None:
    normalized = re.sub(r"^\s*--.*$", "", stmt.strip(), flags=re.MULTILINE).strip().lower()
    if not re.match(r"^(select|with|pragma)\b", normalized):
        raise ValueError("Only read-only SQL is allowed.")

    forbidden = re.compile(
        r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|vacuum|reindex)\b",
        flags=re.IGNORECASE,
    )
    if forbidden.search(normalized):
        raise ValueError("SQL contains a forbidden write/schema keyword.")
