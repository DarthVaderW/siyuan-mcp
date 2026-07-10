"""Offline unit tests for server.py's security guards and core tool surface.

No live SiYuan kernel required: call_siyuan is mocked throughout. Covers the
guards named in docs/REPAIR_PLAN_2026-07-10.md P1.1 -- assert_read_only_sql,
sql_string, assert_api_endpoint, and the SIYUAN_ALLOW_RAW_API gate on
siyuan_call_api -- plus offline smoke tests for the server.py tools those
guards protect (siyuan_sql_query, siyuan_search_blocks,
siyuan_find_docs_by_attrs). Each test asserts the actually implemented
behavior; see inline notes where that differs from a naive reading of the
function names (e.g. assert_api_endpoint is a prefix + traversal guard, not a
curated endpoint allowlist).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from siyuan_mcp import core as C
from siyuan_mcp import server as S


def _unreachable(endpoint: str, payload: dict[str, Any]) -> Any:
    raise AssertionError(f"call_siyuan should not be reached: {endpoint} {payload}")


@contextmanager
def fake_call_siyuan(
    fn: Callable[[str, dict[str, Any]], Any] = _unreachable,
) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    """Patch server.py's own call_siyuan binding and record every call.

    server.py imports call_siyuan by name (`from siyuan_mcp.core import
    call_siyuan, ...`), so patching core.call_siyuan would not be seen by
    server.py's tools -- they must be patched via their own module binding.
    Defaults to a `fn` that fails the test if reached at all, for guard tests
    that expect rejection before any SiYuan call.
    """
    calls: list[tuple[str, dict[str, Any]]] = []

    def recording(endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        payload = payload or {}
        calls.append((endpoint, payload))
        return fn(endpoint, payload)

    original = S.call_siyuan
    S.call_siyuan = recording  # type: ignore[assignment]
    try:
        yield calls
    finally:
        S.call_siyuan = original  # type: ignore[assignment]


@contextmanager
def allow_raw_api(enabled: bool) -> Iterator[None]:
    """Flip the SIYUAN_ALLOW_RAW_API gate for one test, then restore it.

    current_allow_raw_api() returns core.ALLOW_RAW_API, a module-level
    constant parsed from os.getenv("SIYUAN_ALLOW_RAW_API", ...) once at
    import time -- it does not re-read the environment on each call. Setting
    os.environ alone would therefore not change behavior post-import; this
    flips the parsed flag directly (the thing that actually governs
    siyuan_call_api) and mirrors os.environ alongside it, saving and
    restoring both so no test leaks state into another.
    """
    original_flag = C.ALLOW_RAW_API
    original_env = os.environ.get("SIYUAN_ALLOW_RAW_API")
    C.ALLOW_RAW_API = enabled
    os.environ["SIYUAN_ALLOW_RAW_API"] = "true" if enabled else "false"
    try:
        yield
    finally:
        C.ALLOW_RAW_API = original_flag
        if original_env is None:
            os.environ.pop("SIYUAN_ALLOW_RAW_API", None)
        else:
            os.environ["SIYUAN_ALLOW_RAW_API"] = original_env


# --- assert_read_only_sql (server.py) ----------------------------------------


def test_assert_read_only_sql_allows_select_with_pragma_forms() -> None:
    for stmt in (
        "SELECT * FROM blocks",
        "select * from blocks",
        "SeLeCt * FROM blocks",
        "  SELECT 1",
        "\n\t SELECT 1",
        "WITH cte AS (SELECT 1) SELECT * FROM cte",
        "with cte as (select 1) select * from cte",
        "PRAGMA table_info(blocks)",
        "pragma table_info(blocks)",
        "-- setup comment\nSELECT 1",
    ):
        S.assert_read_only_sql(stmt)  # must not raise


def test_assert_read_only_sql_does_not_false_positive_on_substrings() -> None:
    # "updated" contains "update" but is not the keyword: the forbidden-word
    # regex is genuinely \b-bounded, so this must pass. Real implemented
    # behavior, not an invented guarantee.
    S.assert_read_only_sql("SELECT * FROM blocks WHERE content LIKE '%updated%'")
    S.assert_read_only_sql("SELECT created, updated FROM blocks")


def test_assert_read_only_sql_rejects_non_select_statements() -> None:
    for stmt in (
        "INSERT INTO blocks VALUES (1)",
        "insert into blocks values (1)",
        "InSeRt INTO blocks VALUES (1)",
        "  DELETE FROM blocks",
        "\ndelete from blocks",
        "UPDATE blocks SET content = 'x'",
        "DROP TABLE blocks",
        "ALTER TABLE blocks ADD COLUMN x",
        "CREATE TABLE x (y int)",
        "REPLACE INTO blocks VALUES (1)",
        "TRUNCATE TABLE blocks",
        "ATTACH DATABASE 'x' AS y",
        "DETACH DATABASE y",
        "VACUUM",
        "REINDEX blocks",
        "",
        "   ",
    ):
        try:
            S.assert_read_only_sql(stmt)
            raise AssertionError(f"expected ValueError for {stmt!r}")
        except ValueError as error:
            assert "read-only" in str(error).lower()


def test_assert_read_only_sql_rejects_forbidden_keyword_after_select() -> None:
    for stmt in (
        "SELECT * FROM blocks; DROP TABLE blocks;",
        "select * from blocks; drop table blocks;",
        "SELECT * FROM blocks; DrOp TABLE blocks;",
        "WITH cte AS (DELETE FROM blocks) SELECT * FROM cte",
    ):
        try:
            S.assert_read_only_sql(stmt)
            raise AssertionError(f"expected ValueError for {stmt!r}")
        except ValueError as error:
            assert "forbidden" in str(error).lower()


# --- sql_string (server.py) --------------------------------------------------


def test_sql_string_wraps_and_escapes_quotes() -> None:
    assert S.sql_string("abc") == "'abc'"
    assert S.sql_string("") == "''"
    assert S.sql_string("it's") == "'it''s'"
    assert S.sql_string("a'b'c") == "'a''b''c'"


def test_sql_string_does_not_escape_like_wildcards() -> None:
    # Actual implemented behavior: sql_string only escapes single quotes. It
    # has no LIKE-wildcard handling, so callers that interpolate user input
    # into a LIKE pattern (siyuan_search_blocks, siyuan_find_docs_by_attrs)
    # pass % and _ through unescaped -- a semantic wildcard-leak, not an
    # injection risk (quotes are still safely escaped either way).
    assert S.sql_string("50%_off") == "'50%_off'"
    assert S.sql_string("%") == "'%'"
    assert S.sql_string("_") == "'_'"


def test_sql_string_neutralizes_quote_breakout_attempt() -> None:
    escaped = S.sql_string("x' OR '1'='1")
    assert escaped == "'x'' OR ''1''=''1'"
    # No lone unescaped quote remains inside the literal that could close it
    # early -- every quote from the input is now part of a doubled pair.
    inner = escaped[1:-1]
    assert inner.count("'") % 2 == 0


# --- assert_api_endpoint (core.py) -------------------------------------------
#
# Not a curated allowlist of endpoint names: the actual implementation is a
# prefix + path-traversal guard (must start with "/api/", must not contain
# ".."). Tested as implemented.


def test_assert_api_endpoint_accepts_api_prefixed_paths() -> None:
    for endpoint in ("/api/notebook/lsNotebooks", "/api/query/sql", "/api/system/getConf"):
        C.assert_api_endpoint(endpoint)  # must not raise


def test_assert_api_endpoint_rejects_non_api_prefix() -> None:
    for endpoint in ("/foo/bar", "api/notebook/lsNotebooks", "", "notebook/lsNotebooks"):
        try:
            C.assert_api_endpoint(endpoint)
            raise AssertionError(f"expected ValueError for {endpoint!r}")
        except ValueError as error:
            assert "must start with /api/" in str(error)


def test_assert_api_endpoint_rejects_path_traversal() -> None:
    for endpoint in (
        "/api/../etc/passwd",
        "/api/notebook/../../../etc/passwd",
        "/api/..",
        "/api/a/../b",
    ):
        try:
            C.assert_api_endpoint(endpoint)
            raise AssertionError(f"expected ValueError for {endpoint!r}")
        except ValueError as error:
            assert "cannot contain '..'" in str(error)


# --- siyuan_call_api: disabled by default, gated by SIYUAN_ALLOW_RAW_API -----


def test_siyuan_call_api_disabled_by_default() -> None:
    with allow_raw_api(False), fake_call_siyuan() as calls:
        try:
            S.siyuan_call_api("/api/notebook/lsNotebooks")
            raise AssertionError("expected PermissionError when raw API is disabled")
        except PermissionError as error:
            assert "SIYUAN_ALLOW_RAW_API" in str(error)
    assert calls == []


def test_siyuan_call_api_enabled_via_env_flag() -> None:
    with allow_raw_api(True), fake_call_siyuan(lambda e, p: {"ok": True, "seen": p}) as calls:
        result = S.siyuan_call_api("/api/notebook/lsNotebooks", {"x": 1})

    assert result == {
        "endpoint": "/api/notebook/lsNotebooks",
        "result": {"ok": True, "seen": {"x": 1}},
    }
    assert calls == [("/api/notebook/lsNotebooks", {"x": 1})]


def test_siyuan_call_api_still_enforces_endpoint_guard_when_enabled() -> None:
    with allow_raw_api(True), fake_call_siyuan() as calls:
        try:
            S.siyuan_call_api("/not-an-api/path")
            raise AssertionError("expected ValueError for a non-/api/ endpoint")
        except ValueError as error:
            assert "must start with /api/" in str(error)
    assert calls == []


# --- offline smoke tests: siyuan_sql_query -----------------------------------


def test_siyuan_sql_query_happy_path_and_truncation() -> None:
    rows = [{"id": f"id{i}"} for i in range(5)]
    with fake_call_siyuan(lambda e, p: rows) as calls:
        result = S.siyuan_sql_query("SELECT id FROM blocks", limit=3)

    assert calls == [("/api/query/sql", {"stmt": "SELECT id FROM blocks"})]
    assert result["rows"] == rows[:3]
    assert result["truncated"] is True


def test_siyuan_sql_query_rejects_write_before_calling_siyuan() -> None:
    with fake_call_siyuan() as calls:
        try:
            S.siyuan_sql_query("DELETE FROM blocks")
            raise AssertionError("expected ValueError for a write statement")
        except ValueError as error:
            assert "read-only" in str(error).lower()
    assert calls == []


def test_siyuan_sql_query_rejects_out_of_range_limit() -> None:
    with fake_call_siyuan() as calls:
        for limit in (0, 501, -1):
            try:
                S.siyuan_sql_query("SELECT 1", limit=limit)
                raise AssertionError(f"expected ValueError for limit={limit}")
            except ValueError:
                pass
    assert calls == []


# --- offline smoke tests: siyuan_search_blocks -------------------------------


def test_siyuan_search_blocks_escapes_keyword_into_like_pattern() -> None:
    with fake_call_siyuan(lambda e, p: []) as calls:
        S.siyuan_search_blocks("O'Brien")

    assert len(calls) == 1
    endpoint, payload = calls[0]
    assert endpoint == "/api/query/sql"
    assert "content LIKE '%O''Brien%'" in payload["stmt"]


def test_siyuan_search_blocks_appends_type_filter() -> None:
    with fake_call_siyuan(lambda e, p: []) as calls:
        S.siyuan_search_blocks("hello", type="d")

    assert "type = 'd'" in calls[0][1]["stmt"]


def test_siyuan_search_blocks_rejects_out_of_range_limit() -> None:
    with fake_call_siyuan() as calls:
        for limit in (0, 101):
            try:
                S.siyuan_search_blocks("hello", limit=limit)
                raise AssertionError(f"expected ValueError for limit={limit}")
            except ValueError:
                pass
    assert calls == []


# --- offline smoke tests: siyuan_find_docs_by_attrs --------------------------


def test_siyuan_find_docs_by_attrs_escapes_value_into_stmt() -> None:
    with fake_call_siyuan(lambda e, p: []) as calls:
        result = S.siyuan_find_docs_by_attrs({"custom-project": "It's a test"})

    assert len(calls) == 1
    assert calls[0][1]["stmt"] == result["stmt"]
    assert """ial LIKE '%custom-project="It''s a test"%'""" in result["stmt"]


def test_siyuan_find_docs_by_attrs_none_value_checks_key_presence_only() -> None:
    with fake_call_siyuan(lambda e, p: []) as calls:
        result = S.siyuan_find_docs_by_attrs({"custom-flag": None})

    assert "ial LIKE '%custom-flag=%'" in result["stmt"]
    assert calls


def test_siyuan_find_docs_by_attrs_rejects_invalid_key_before_calling_siyuan() -> None:
    with fake_call_siyuan() as calls:
        try:
            S.siyuan_find_docs_by_attrs({"bad key!": "x"})
            raise AssertionError("expected ValueError for an invalid attribute key")
        except ValueError as error:
            assert "Invalid attribute key" in str(error)
    assert calls == []


def test_siyuan_find_docs_by_attrs_rejects_empty_attrs() -> None:
    with fake_call_siyuan() as calls:
        try:
            S.siyuan_find_docs_by_attrs({})
            raise AssertionError("expected ValueError for empty attrs")
        except ValueError as error:
            assert "attrs cannot be empty" in str(error)
    assert calls == []


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
