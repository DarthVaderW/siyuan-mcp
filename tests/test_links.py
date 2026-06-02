"""Offline unit tests for generic SiYuan link helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from siyuan_research_mcp import core as C
from siyuan_research_mcp import links as L


def response_key(endpoint: str, payload: dict[str, Any]) -> tuple[str, str]:
    return (endpoint, json.dumps(payload, ensure_ascii=False, sort_keys=True))


@contextmanager
def fake_siyuan(responses: dict[tuple[str, str], Any], default_notebook: str = "CodeX") -> Iterator[None]:
    original_call = C.call_siyuan
    original_default = C.current_default_notebook

    def call(endpoint: str, payload: dict[str, Any]) -> Any:
        key = response_key(endpoint, payload)
        if key not in responses:
            raise AssertionError(f"unexpected SiYuan call: {endpoint} {payload}")
        return responses[key]

    C.call_siyuan = call  # type: ignore[assignment]
    C.current_default_notebook = lambda: default_notebook  # type: ignore[assignment]
    try:
        yield
    finally:
        C.call_siyuan = original_call  # type: ignore[assignment]
        C.current_default_notebook = original_default  # type: ignore[assignment]


def test_validate_block_id() -> None:
    assert L.validate_block_id("20260602233246-8islm9u") == "20260602233246-8islm9u"
    assert L.validate_block_id(" 20260602233246-8islm9u ") == "20260602233246-8islm9u"

    for value in ("", "abc", "20260602233246", "20260602233246-TOOLONG", "20260602233246-ABC1234"):
        try:
            L.validate_block_id(value)
            raise AssertionError(f"expected invalid id for {value!r}")
        except ValueError:
            pass


def test_format_block_link() -> None:
    result = L.format_block_link("20260602233246-8islm9u", "经验库 README")
    assert result == {
        "id": "20260602233246-8islm9u",
        "label": "经验库 README",
        "url": "siyuan://blocks/20260602233246-8islm9u",
        "markdown": "[经验库 README](siyuan://blocks/20260602233246-8islm9u)",
    }

    escaped = L.format_block_link("20260602233246-8islm9u", r"a[b]c\\d")
    assert escaped["markdown"] == r"[a\[b\]c\\\\d](siyuan://blocks/20260602233246-8islm9u)"

    newline = L.format_block_link("20260602233246-8islm9u", "a\nb")
    assert newline["markdown"] == "[a b](siyuan://blocks/20260602233246-8islm9u)"

    try:
        L.format_block_link("20260602233246-8islm9u", " ")
        raise AssertionError("expected missing label error")
    except ValueError:
        pass


def test_derive_label_from_hpath() -> None:
    assert L.derive_label_from_hpath("/MCP/经验库/README") == "README"
    assert L.derive_label_from_hpath("MCP//经验库//README/") == "README"
    assert L.derive_label_from_hpath("/") == "SiYuan document"
    assert L.derive_label_from_hpath("") == "SiYuan document"


def test_normalize_doc_path() -> None:
    assert L.normalize_doc_path("MCP\\经验库//README") == "/MCP/经验库/README"
    assert L.normalize_doc_path("/MCP/经验库/README") == "/MCP/经验库/README"

    try:
        L.normalize_doc_path(" ")
        raise AssertionError("expected empty path error")
    except ValueError:
        pass


def test_format_doc_link() -> None:
    result = L.format_doc_link({"id": "20260602233246-8islm9u", "hpath": "/MCP/经验库/README"})
    assert result["found"] is True
    assert result["ambiguous"] is False
    assert result["label"] == "README"
    assert result["markdown"] == "[README](siyuan://blocks/20260602233246-8islm9u)"

    custom = L.format_doc_link(
        {"id": "20260602233246-8islm9u", "hpath": "/MCP/经验库/README"},
        "经验库 README",
    )
    assert custom["label"] == "经验库 README"
    assert custom["markdown"] == "[经验库 README](siyuan://blocks/20260602233246-8islm9u)"

    try:
        L.format_doc_link({"hpath": "/MCP/经验库/README"})
        raise AssertionError("expected missing id error")
    except ValueError as error:
        assert "missing 'id'" in str(error)


def test_extract_doc_ids() -> None:
    assert L.extract_doc_ids(["a", {"id": "b"}, None, {}]) == ["a", "b"]
    assert L.extract_doc_ids({"ids": ["a", {"id": "b"}]}) == ["a", "b"]
    assert L.extract_doc_ids({"id": "single"}) == ["single"]
    assert L.extract_doc_ids({"ids": []}) == []
    assert L.extract_doc_ids(None) == []


def test_make_doc_link_found() -> None:
    responses = {
        response_key("/api/notebook/lsNotebooks", {}): [{"id": "box-id", "name": "CodeX"}],
        response_key(
            "/api/filetree/getIDsByHPath",
            {"notebook": "box-id", "path": "/MCP/经验库/README"},
        ): [{"id": "20260602233246-8islm9u"}],
        response_key(
            "/api/filetree/getHPathByID",
            {"id": "20260602233246-8islm9u"},
        ): "/MCP/经验库/README",
    }
    with fake_siyuan(responses):
        result = L.siyuan_make_doc_link("/MCP/经验库/README")

    assert result["found"] is True
    assert result["ambiguous"] is False
    assert result["notebook"] == "box-id"
    assert result["label"] == "README"
    assert result["markdown"] == "[README](siyuan://blocks/20260602233246-8islm9u)"


def test_make_doc_link_missing() -> None:
    responses = {
        response_key("/api/notebook/lsNotebooks", {}): [{"id": "box-id", "name": "CodeX"}],
        response_key(
            "/api/filetree/getIDsByHPath",
            {"notebook": "box-id", "path": "/missing"},
        ): [],
    }
    with fake_siyuan(responses):
        result = L.siyuan_make_doc_link("/missing")

    assert result == {
        "found": False,
        "ambiguous": False,
        "notebook": "box-id",
        "path": "/missing",
        "label": "missing",
        "candidates": [],
    }


def test_make_doc_link_ambiguous() -> None:
    responses = {
        response_key("/api/notebook/lsNotebooks", {}): [{"id": "box-id", "name": "CodeX"}],
        response_key(
            "/api/filetree/getIDsByHPath",
            {"notebook": "box-id", "path": "/README"},
        ): [{"id": "20260602233246-8islm9u"}, {"id": "20260602233315-3k8urx7"}],
        response_key(
            "/api/filetree/getHPathByID",
            {"id": "20260602233246-8islm9u"},
        ): "/A/README",
        response_key(
            "/api/filetree/getHPathByID",
            {"id": "20260602233315-3k8urx7"},
        ): "/B/README",
    }
    with fake_siyuan(responses):
        result = L.siyuan_make_doc_link("/README")

    assert result["found"] is False
    assert result["ambiguous"] is True
    assert result["label"] == "README"
    assert result["candidateCount"] == 2
    assert result["returnedCandidateCount"] == 2
    assert result["candidatesTruncated"] is False
    assert [item["hpath"] for item in result["candidates"]] == ["/A/README", "/B/README"]


def test_make_doc_link_explicit_notebook_name() -> None:
    responses = {
        response_key("/api/notebook/lsNotebooks", {}): [{"id": "box-id", "name": "Daily"}],
        response_key(
            "/api/filetree/getIDsByHPath",
            {"notebook": "box-id", "path": "/Daily/2026"},
        ): [{"id": "20260602233246-8islm9u"}],
        response_key(
            "/api/filetree/getHPathByID",
            {"id": "20260602233246-8islm9u"},
        ): "/Daily/2026",
    }
    with fake_siyuan(responses):
        result = L.siyuan_make_doc_link("Daily/2026", notebook="Daily")

    assert result["found"] is True
    assert result["notebook"] == "box-id"
    assert result["path"] == "/Daily/2026"


def test_make_doc_link_explicit_notebook_id_skips_notebook_list() -> None:
    notebook_id = "20260602000000-abcde00"
    responses = {
        response_key(
            "/api/filetree/getIDsByHPath",
            {"notebook": notebook_id, "path": "/MCP/经验库/README"},
        ): [{"id": "20260602233246-8islm9u"}],
        response_key(
            "/api/filetree/getHPathByID",
            {"id": "20260602233246-8islm9u"},
        ): "/MCP/经验库/README",
    }
    with fake_siyuan(responses):
        result = L.siyuan_make_doc_link("/MCP/经验库/README", notebook=notebook_id)

    assert result["found"] is True
    assert result["notebook"] == notebook_id


def test_make_doc_link_requires_notebook() -> None:
    with fake_siyuan({}, default_notebook=""):
        try:
            L.siyuan_make_doc_link("/MCP/经验库/README")
            raise AssertionError("expected notebook error")
        except ValueError as error:
            assert "Notebook is required" in str(error)


def test_candidate_links_are_capped() -> None:
    ids = [f"202606020000{i:02d}-abcde{i:02d}" for i in range(12)]
    responses: dict[tuple[str, str], Any] = {
        response_key("/api/notebook/lsNotebooks", {}): [{"id": "box-id", "name": "CodeX"}],
        response_key(
            "/api/filetree/getIDsByHPath",
            {"notebook": "box-id", "path": "/README"},
        ): [{"id": doc_id} for doc_id in ids],
    }
    for index, doc_id in enumerate(ids[: L.MAX_CANDIDATE_LINKS]):
        responses[response_key("/api/filetree/getHPathByID", {"id": doc_id})] = f"/Candidate/{index}/README"

    with fake_siyuan(responses):
        result = L.siyuan_make_doc_link("/README")

    assert result["candidateCount"] == 12
    assert result["returnedCandidateCount"] == L.MAX_CANDIDATE_LINKS
    assert result["candidatesTruncated"] is True
    assert len(result["candidates"]) == L.MAX_CANDIDATE_LINKS


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
