"""Offline unit tests for KMind helpers (no live SiYuan kernel required)."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from siyuan_research_mcp import kmind as K


def test_html_text_and_rich_text() -> None:
    assert K.kmind_html_text("<p><span>基于运动学</span></p>") == "基于运动学"
    assert K.kmind_html_text("<p>a &amp; b</p>") == "a & b"
    assert K.kmind_html_text(None) == ""
    assert K.make_rich_text("hello") == "<p>hello</p>"
    assert K.make_rich_text("a & b") == "<p>a &amp; b</p>"


def test_uid_format() -> None:
    uid = K.generate_kmind_uid()
    assert re.match(r"^kmind-node-\d{17}-[0-9a-f]{8}$", uid), uid


def test_walk_and_find() -> None:
    root = {
        "data": {"text": "<p>root</p>", "uid": "u-root"},
        "children": [
            {"data": {"text": "<p>a</p>", "uid": "u-a"}, "children": [
                {"data": {"text": "<p>a1</p>", "uid": "u-a1"}, "children": []},
            ]},
            {"data": {"text": "<p>b</p>", "uid": "u-b"}, "children": []},
        ],
    }
    assert K.count_nodes(root) == 4
    assert K.find_node_by_uid(root, "u-a1")["data"]["uid"] == "u-a1"
    assert K.find_node_by_uid(root, "missing") is None
    assert len(K.find_nodes_by_text(root, "a1")) == 1

    depths = {K.node_plain_text(n): d for n, d, _p in K.walk_kmind_nodes(root)}
    assert depths == {"root": 0, "a": 1, "a1": 2, "b": 1}

    outline = K._outline(root, max_depth=1, include_styles=False)
    assert [o["text"] for o in outline] == ["root", "a", "b"]
    assert K._outline_markdown(root, None) == "- root\n  - a\n    - a1\n  - b"


def test_apply_node_style_guards() -> None:
    data: dict = {}
    changed = K.apply_node_style(data, {"fillColor": "red", "fontSize": 14})
    assert set(changed) == {"fillColor", "fontSize"}
    assert data == {"fillColor": "red", "fontSize": 14}

    # lineColor is not a node style; must be rejected in node_style.
    try:
        K.apply_node_style({}, {"lineColor": "x"})
        raise AssertionError("expected ValueError for lineColor in node_style")
    except ValueError:
        pass

    # line_style accepts lineColor/lineWidth.
    d2: dict = {}
    K.apply_node_style(d2, {}, {"lineColor": "rgb(1,2,3)", "lineWidth": 2})
    assert d2 == {"lineColor": "rgb(1,2,3)", "lineWidth": 2}


def test_dump_is_compact_and_roundtrips() -> None:
    data = {"root": {"data": {"text": "<p>中文</p>", "uid": "u"}, "children": []}}
    raw = K.dump_kmind_bytes(data)
    assert b" " not in raw  # compact (no spaces between tokens)
    assert "中文".encode("utf-8") in raw  # not ascii-escaped
    assert json.loads(raw.decode("utf-8")) == data


def test_make_node() -> None:
    node = K.make_node("hi", {"color": "blue"})
    assert node["data"]["text"] == "<p>hi</p>"
    assert node["data"]["richText"] is True
    assert node["data"]["color"] == "blue"
    assert node["children"] == []
    assert re.match(r"^kmind-node-", node["data"]["uid"])


def test_backup_retention_per_doc_count() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        index = []
        # Recent timestamps so the age limit does not interfere with the count test.
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        # 25 backups for one doc; limit is 20 -> oldest 5 dropped.
        for i in range(25):
            name = f"b{i:02d}.kmind"
            (backup_dir / name).write_bytes(b"{}")
            index.append({
                "docId": "doc1",
                "createdAt": (base + timedelta(minutes=i)).isoformat(),
                "sizeBytes": 2,
                "backupPath": name,
            })
        kept = K.cleanup_kmind_backups(backup_dir, index)
        assert len(kept) == K.MAX_BACKUPS_PER_DOC == 20
        # The 5 oldest files are gone from disk.
        assert not (backup_dir / "b00.kmind").exists()
        assert (backup_dir / "b24.kmind").exists()


def test_backup_retention_age_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        old = (backup_dir / "old.kmind")
        new = (backup_dir / "new.kmind")
        old.write_bytes(b"{}")
        new.write_bytes(b"{}")
        index = [
            {"docId": "d", "createdAt": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
             "sizeBytes": 2, "backupPath": "old.kmind"},
            {"docId": "d", "createdAt": datetime.now(timezone.utc).isoformat(),
             "sizeBytes": 2, "backupPath": "new.kmind"},
        ]
        kept = K.cleanup_kmind_backups(backup_dir, index)
        assert [e["backupPath"] for e in kept] == ["new.kmind"]
        assert not old.exists() and new.exists()


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
