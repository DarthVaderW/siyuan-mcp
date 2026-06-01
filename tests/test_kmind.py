"""Offline unit tests for KMind helpers (no live SiYuan kernel required)."""

from __future__ import annotations

import copy
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


# --- P0: strict "untouched subtree unchanged" regression --------------------
#
# These lock the core safety invariant the rest of the KMind safety layer rests
# on (docs/KMIND_ASSESSMENT.md, converged spec): an edit to one node must never
# silently alter an unrelated node's data, and must never repaint another
# branch's connector line. They are pure in-memory (no live SiYuan kernel,
# no disk, no network) and mirror the exact mutate sequences of the
# siyuan_kmind_add_node / siyuan_kmind_style_node tools using the real kmind
# helpers. If those tool closures change, update these to match.


def _sample_tree() -> dict:
    """A small KMind doc with several hand-styled branches (distinct lineColors)."""
    return {
        "root": {
            "data": {"text": "<p>论文梳理</p>", "uid": "u-root", "expand": True},
            "children": [
                {
                    "data": {
                        "text": "<p>运动学</p>", "uid": "u-kin",
                        "fillColor": "rgb(255,255,255)",
                        "lineColor": "rgb(237,185,81)",  # hand-styled yellow branch
                        "lineWidth": 2,
                        "fontSize": 16,
                    },
                    "children": [
                        {"data": {"text": "<p>正运动学</p>", "uid": "u-fk",
                                  "lineColor": "rgb(237,185,81)"}, "children": []},
                        {"data": {"text": "<p>逆运动学</p>", "uid": "u-ik"}, "children": []},
                    ],
                },
                {
                    "data": {"text": "<p>动力学</p>", "uid": "u-dyn",
                             "lineColor": "rgb(50,100,200)", "color": "rgb(0,0,0)"},
                    "children": [
                        {"data": {"text": "<p>拉格朗日</p>", "uid": "u-lag"}, "children": []},
                    ],
                },
            ],
        }
    }


def _snapshot_data_by_uid(root: dict) -> dict:
    """{uid: deepcopy(node data)} for every node, for byte-for-byte comparison."""
    return {
        K.node_uid(n): copy.deepcopy(n.get("data", {}))
        for n, _d, _p in K.walk_kmind_nodes(root)
        if K.node_uid(n)
    }


def _assert_no_line_field_changes(root: dict, before: dict, exempt: set | None = None) -> None:
    """Assert no node's lineColor/lineWidth differs from `before` (except `exempt`).

    New nodes (uid absent from `before`) must carry no line fields at all.
    """
    exempt = exempt or set()
    for node, _d, _p in K.walk_kmind_nodes(root):
        uid = K.node_uid(node)
        if uid in exempt:
            continue
        data = node.get("data", {})
        if uid not in before:
            for field in K.LINE_STYLE_FIELDS:
                assert field not in data, f"new node {uid} gained line field {field!r}"
            continue
        prior = before[uid]
        for field in K.LINE_STYLE_FIELDS:
            assert (field in data) == (field in prior), (
                f"line field {field!r} presence on node {uid} changed: "
                f"{field in prior!r} -> {field in data!r}"
            )
            assert data.get(field) == prior.get(field), (
                f"line field {field!r} on node {uid} changed: "
                f"{prior.get(field)!r} -> {data.get(field)!r}"
            )


def test_add_node_leaves_existing_subtree_unchanged() -> None:
    """add_node must not alter any pre-existing node's data, nor add line style."""
    data = _sample_tree()
    root = K._require_root(data)
    before = _snapshot_data_by_uid(root)

    # Mirror siyuan_kmind_add_node's mutate(): locate parent, build the node
    # (with children), append under the parent. No existing node is touched.
    parent = K._locate_parent(root, "u-kin", None)
    new_node = K.make_node("微分运动学", {"fillColor": "rgb(200,200,200)"})
    for child_text in ["雅可比", "奇异性"]:
        new_node["children"].append(K.make_node(child_text))
    parent.setdefault("children", []).append(new_node)

    # (a) every pre-existing node's data is byte-for-byte identical.
    after = {K.node_uid(n): n.get("data", {}) for n, _d, _p in K.walk_kmind_nodes(root)}
    for uid, snapshot in before.items():
        assert after[uid] == snapshot, f"existing node {uid} data changed"

    # (b) no node anywhere gained/changed lineColor or lineWidth; the new node
    #     and its children are created unstyled (no line fields).
    _assert_no_line_field_changes(root, before)
    assert "lineColor" not in new_node["data"] and "lineWidth" not in new_node["data"]

    # The new node was appended last under the chosen parent and nothing else moved.
    assert K.node_uid(parent["children"][-1]) == K.node_uid(new_node)
    assert K.count_nodes(root) == len(before) + 3  # new node + its 2 children


def test_style_node_changes_only_declared_fields_on_target() -> None:
    """style_node (node_style only) must change only the target's declared fields."""
    data = _sample_tree()
    root = K._require_root(data)
    before = _snapshot_data_by_uid(root)
    target_uid = "u-dyn"

    # Mirror siyuan_kmind_style_node's mutate() with node_style only (no line_style).
    target = K._locate_target(root, target_uid, None)
    node_style = {"fillColor": "rgb(255,0,0)", "fontSize": 22}
    changed = K.apply_node_style(target["data"], node_style, None)
    assert set(changed) == set(node_style)

    after = _snapshot_data_by_uid(root)
    # (a) every non-target node is byte-for-byte identical.
    for uid, snapshot in before.items():
        if uid == target_uid:
            continue
        assert after[uid] == snapshot, f"non-target node {uid} changed"

    # (c) the target changed only the declared fields.
    diff = {
        k for k in set(before[target_uid]) | set(after[target_uid])
        if before[target_uid].get(k) != after[target_uid].get(k)
    }
    assert diff == set(node_style), diff

    # (b) with no line_style, no node anywhere (incl. the target) changed line fields.
    _assert_no_line_field_changes(root, before)


def test_style_node_line_style_does_not_repaint_siblings() -> None:
    """An explicit line_style on one node must not repaint any other branch."""
    data = _sample_tree()
    root = K._require_root(data)
    before = _snapshot_data_by_uid(root)
    target_uid = "u-fk"  # currently yellow rgb(237,185,81)

    target = K._locate_target(root, target_uid, None)
    node_style = {"color": "rgb(10,20,30)"}
    line_style = {"lineColor": "rgb(0,0,255)", "lineWidth": 4}
    changed = K.apply_node_style(target["data"], node_style, line_style)
    assert set(changed) == set(node_style) | set(line_style)

    after = _snapshot_data_by_uid(root)
    # (a) every non-target node is byte-for-byte identical.
    for uid, snapshot in before.items():
        if uid == target_uid:
            continue
        assert after[uid] == snapshot, f"non-target node {uid} changed"

    # (c) only the target's declared fields changed.
    diff = {
        k for k in set(before[target_uid]) | set(after[target_uid])
        if before[target_uid].get(k) != after[target_uid].get(k)
    }
    assert diff == set(node_style) | set(line_style), diff

    # (b) only the target's line fields changed; sibling branches keep their lines.
    _assert_no_line_field_changes(root, before, exempt={target_uid})
    assert after[target_uid]["lineColor"] == "rgb(0,0,255)"
    assert after[target_uid]["lineWidth"] == 4
    assert after["u-kin"]["lineColor"] == "rgb(237,185,81)"
    assert after["u-dyn"]["lineColor"] == "rgb(50,100,200)"


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


def test_backup_same_second_collision_keeps_both_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        asset = data_dir / "assets" / "map.kmind"
        asset.parent.mkdir()
        asset.write_bytes(b'{"root":{"data":{"text":"<p>x</p>"},"children":[]}}')

        first = K.write_backup(
            data_dir=data_dir,
            asset_abs=asset,
            asset_rel="assets/map.kmind",
            doc_id="doc1",
            operation="add-node",
            sha256_before="sha1",
            size_bytes=asset.stat().st_size,
            timestamp="20260601-120000-000000",
        )
        second = K.write_backup(
            data_dir=data_dir,
            asset_abs=asset,
            asset_rel="assets/map.kmind",
            doc_id="doc1",
            operation="add-node",
            sha256_before="sha2",
            size_bytes=asset.stat().st_size,
            timestamp="20260601-120000-000000",
        )

        backup_dir = data_dir.joinpath(*K.BACKUP_REL_DIR)
        assert first != second
        assert (backup_dir / first).exists()
        assert (backup_dir / second).exists()
        index = json.loads((backup_dir / K.BACKUP_INDEX_NAME).read_text())
        assert [entry["backupPath"] for entry in index] == [first, second]


# --- P1: siyuan_kmind_diff (read-only, style-aware) -------------------------
#
# All offline: diff_kmind_trees and resolve_diff_reference are pure helpers that
# take in-memory trees / a backup dir + index, so they need no live SiYuan. The
# siyuan_kmind_diff tool is a thin wrapper over them (it only adds SiYuan doc
# resolution), so exercising the helpers covers the diff logic.


def _write_kmind(path: Path, tree: dict) -> str:
    """Write a tree as a compact .kmind file; return its sha256 (as backups store)."""
    raw = K.dump_kmind_bytes(tree)
    path.write_bytes(raw)
    return K._sha256(raw)


def test_classify_kmind_field() -> None:
    assert K.classify_kmind_field("text") == "content"
    assert K.classify_kmind_field("note") == "content"
    assert K.classify_kmind_field("fillColor") == "nodeStyle"
    assert K.classify_kmind_field("fontSize") == "nodeStyle"
    assert K.classify_kmind_field("lineColor") == "branchLine"
    assert K.classify_kmind_field("lineWidth") == "branchLine"
    assert K.classify_kmind_field("expand") == "other"
    assert K.classify_kmind_field("richText") == "other"


def test_diff_kmind_trees_identical_is_empty() -> None:
    tree = _sample_tree()
    diff = K.diff_kmind_trees(K._require_root(copy.deepcopy(tree)), K._require_root(tree))
    assert diff["added"] == [] and diff["removed"] == [] and diff["changed"] == []
    s = diff["summary"]
    assert (s["added"], s["removed"], s["changed"]) == (0, 0, 0)
    assert s["branchLineChanged"] is False and s["nodeStyleChanged"] is False
    assert s["fieldChangesByBucket"] == {"content": 0, "nodeStyle": 0, "branchLine": 0, "other": 0}


def test_diff_kmind_trees_added_removed_changed() -> None:
    ref_tree = _sample_tree()
    cur_tree = copy.deepcopy(ref_tree)
    cur_root = K._require_root(cur_tree)

    # changed: u-dyn text (content) + new fillColor (nodeStyle) + lineColor (branchLine)
    target = K.find_node_by_uid(cur_root, "u-dyn")
    target["data"]["text"] = "<p>动力学(改)</p>"
    target["data"]["fillColor"] = "rgb(1,2,3)"
    target["data"]["lineColor"] = "rgb(9,9,9)"
    # removed: leaf u-lag
    target["children"] = [c for c in target["children"] if K.node_uid(c) != "u-lag"]
    # added: a fresh child under u-kin
    new_node = K.make_node("新节点")
    K.find_node_by_uid(cur_root, "u-kin")["children"].append(new_node)

    diff = K.diff_kmind_trees(K._require_root(ref_tree), cur_root)

    assert [a["uid"] for a in diff["added"]] == [K.node_uid(new_node)]
    assert [r["uid"] for r in diff["removed"]] == ["u-lag"]
    assert [c["uid"] for c in diff["changed"]] == ["u-dyn"]

    ch = diff["changed"][0]
    assert ch["changedFields"] == {
        "content": ["text"], "nodeStyle": ["fillColor"],
        "branchLine": ["lineColor"], "other": [],
    }
    assert ch["values"]["lineColor"] == {
        "before": "rgb(50,100,200)", "after": "rgb(9,9,9)",
        "beforePresent": True, "afterPresent": True,
    }
    assert ch["values"]["text"]["after"] == "<p>动力学(改)</p>"
    assert ch["values"]["fillColor"] == {
        "before": None, "after": "rgb(1,2,3)",
        "beforePresent": False, "afterPresent": True,
    }

    s = diff["summary"]
    assert (s["added"], s["removed"], s["changed"]) == (1, 1, 1)
    assert s["branchLineChanged"] is True and s["nodeStyleChanged"] is True
    assert s["fieldChangesByBucket"] == {"content": 1, "nodeStyle": 1, "branchLine": 1, "other": 0}
    # added/removed carry a locating path.
    assert diff["added"][0]["path"][-1] == "新节点"
    assert diff["removed"][0]["text"] == "拉格朗日"


def test_diff_kmind_trees_detects_field_presence_change() -> None:
    ref_tree = _sample_tree()
    cur_tree = copy.deepcopy(ref_tree)
    cur_root = K._require_root(cur_tree)
    K.find_node_by_uid(cur_root, "u-ik")["data"]["lineColor"] = None

    diff = K.diff_kmind_trees(K._require_root(ref_tree), cur_root)

    assert [c["uid"] for c in diff["changed"]] == ["u-ik"]
    ch = diff["changed"][0]
    assert ch["changedFields"]["branchLine"] == ["lineColor"]
    assert ch["values"]["lineColor"] == {
        "before": None, "after": None,
        "beforePresent": False, "afterPresent": True,
    }
    assert diff["summary"]["branchLineChanged"] is True


def test_resolve_diff_reference_latest_backup_reports_selection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        old_sha = _write_kmind(backup_dir / "old.kmind", _sample_tree())
        marked = _sample_tree()
        marked["root"]["data"]["text"] = "<p>MARKER</p>"
        new_sha = _write_kmind(backup_dir / "new.kmind", marked)
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        index = [
            {"docId": "docX", "backupPath": "old.kmind", "operation": "add-node",
             "createdAt": base.isoformat(), "sha256Before": old_sha, "sizeBytes": 1},
            {"docId": "docX", "backupPath": "new.kmind", "operation": "style-node",
             "createdAt": (base + timedelta(hours=1)).isoformat(), "sha256Before": new_sha, "sizeBytes": 1},
        ]
        ref = K.resolve_diff_reference(backup_dir, index, "docX")
        assert ref["status"] == "ok"
        # Picked the newest by createdAt, not by file/index order, and reported it.
        report = ref["reference"]
        assert report["kind"] == "latest-backup"
        assert report["backupPath"] == "new.kmind"
        assert report["createdAt"] == index[1]["createdAt"]
        assert report["sha256Before"] == new_sha and report["sha256"] == new_sha
        assert K.node_plain_text(ref["root"]) == "MARKER"


def test_resolve_diff_reference_no_reference_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ref = K.resolve_diff_reference(Path(tmp), [], "docX")
        assert ref["status"] == "no-reference-available"
        assert ref["root"] is None and ref["reference"] is None
        assert "backup" in ref["message"].lower()


def test_resolve_diff_reference_explicit_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ref_file = Path(tmp) / "other.kmind"
        sha = _write_kmind(ref_file, _sample_tree())
        ref = K.resolve_diff_reference(Path(tmp), [], "docX", against_file=str(ref_file))
        assert ref["status"] == "ok"
        assert ref["reference"] == {
            "kind": "file", "filePath": str(ref_file), "sha256": sha, "sizeBytes": ref_file.stat().st_size,
        }
        assert K.node_uid(ref["root"]) == "u-root"


def test_resolve_diff_reference_by_sha() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        sha = _write_kmind(backup_dir / "b.kmind", _sample_tree())
        index = [{"docId": "docX", "backupPath": "b.kmind", "operation": "add-node",
                  "createdAt": datetime.now(timezone.utc).isoformat(), "sha256Before": sha, "sizeBytes": 1}]
        ref = K.resolve_diff_reference(backup_dir, index, "docX", against_sha256=sha)
        assert ref["status"] == "ok" and ref["reference"]["kind"] == "sha256"
        assert ref["reference"]["sha256Before"] == sha
        # Unknown sha must error, not silently fall back.
        try:
            K.resolve_diff_reference(backup_dir, index, "docX", against_sha256="deadbeef")
            raise AssertionError("expected ValueError for unknown sha256")
        except ValueError:
            pass


def test_resolve_diff_reference_by_backup_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        _write_kmind(backup_dir / "b.kmind", _sample_tree())
        index = [{"docId": "docX", "backupPath": "b.kmind", "operation": "add-node",
                  "createdAt": datetime.now(timezone.utc).isoformat(), "sha256Before": "x", "sizeBytes": 1}]
        ref = K.resolve_diff_reference(backup_dir, index, "docX", against_backup_path="b.kmind")
        assert ref["status"] == "ok" and ref["reference"]["kind"] == "backup-path"
        assert ref["reference"]["backupPath"] == "b.kmind"
        assert ref["reference"]["operation"] == "add-node"
        # Missing backup file must raise, not silently diff against nothing.
        try:
            K.resolve_diff_reference(backup_dir, index, "docX", against_backup_path="missing.kmind")
            raise AssertionError("expected FileNotFoundError for missing backup")
        except FileNotFoundError:
            pass


def test_resolve_diff_reference_rejects_multiple_refs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            K.resolve_diff_reference(
                Path(tmp), [], "docX",
                against_backup_path="b.kmind", against_file="x.kmind",
            )
            raise AssertionError("expected ValueError for multiple explicit references")
        except ValueError:
            pass


def test_resolve_diff_reference_rejects_index_path_escape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        backup_dir = root / "backups"
        backup_dir.mkdir()
        escape = root / "escape.kmind"
        _write_kmind(escape, _sample_tree())
        index = [{"docId": "docX", "backupPath": "../escape.kmind",
                  "createdAt": datetime.now(timezone.utc).isoformat(),
                  "sha256Before": "sha-escape"}]

        ref = K.resolve_diff_reference(backup_dir, index, "docX")
        assert ref["status"] == "no-reference-available"
        assert "escapes backup dir" in ref["message"]

        try:
            K.resolve_diff_reference(backup_dir, index, "docX", against_sha256="sha-escape")
            raise AssertionError("expected ValueError for backup path escaping backup dir")
        except ValueError as error:
            assert "escapes backup dir" in str(error)


# --- P2: siyuan_kmind_list_backups (read-only) ------------------------------
#
# Offline: list_kmind_backups is a pure helper over a backup dir + index, so it
# needs no live SiYuan. The siyuan_kmind_list_backups tool only adds doc
# resolution on top of it.


def test_list_kmind_backups_newest_first_and_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        base = datetime.now(timezone.utc) - timedelta(hours=3)
        # docA: a1 present on disk, a2 newer but its file is missing; docB unrelated.
        (backup_dir / "a1.kmind").write_bytes(b"{}")
        (backup_dir / "b1.kmind").write_bytes(b"{}")
        index = [
            {"source": "assets/a.kmind", "docId": "docA", "backupPath": "a1.kmind",
             "operation": "add-node", "createdAt": base.isoformat(),
             "sha256Before": "sha-a1", "sizeBytes": 10},
            {"source": "assets/a.kmind", "docId": "docA", "backupPath": "a2.kmind",
             "operation": "style-node", "createdAt": (base + timedelta(hours=1)).isoformat(),
             "sha256Before": "sha-a2", "sizeBytes": 20},
            {"source": "assets/b.kmind", "docId": "docB", "backupPath": "b1.kmind",
             "operation": "add-node", "createdAt": base.isoformat(),
             "sha256Before": "sha-b1", "sizeBytes": 100},
        ]
        out = K.list_kmind_backups(backup_dir, index, "docA")

        # Only docA, newest first (a2 is newer than a1).
        assert [b["backupPath"] for b in out["backups"]] == ["a2.kmind", "a1.kmind"]
        # The newest entry carries exactly the required fields; its file is gone.
        assert out["backups"][0] == {
            "backupPath": "a2.kmind", "createdAt": index[1]["createdAt"],
            "operation": "style-node", "sha256Before": "sha-a2", "sizeBytes": 20,
            "source": "assets/a.kmind", "existsOnDisk": False,
        }
        assert out["backups"][1]["existsOnDisk"] is True
        # docB excluded; total = 10 + 20; a2's file missing -> missingFiles == 1.
        assert out["summary"] == {
            "count": 2, "totalSizeBytes": 30, "missingFiles": 1,
            "backupDir": str(backup_dir),
        }


def test_list_kmind_backups_empty_is_not_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        out = K.list_kmind_backups(backup_dir, [], "docMissing")
        assert out["backups"] == []
        assert out["summary"] == {
            "count": 0, "totalSizeBytes": 0, "missingFiles": 0,
            "backupDir": str(backup_dir),
        }


def test_list_kmind_backups_filters_by_doc_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        (backup_dir / "x.kmind").write_bytes(b"{}")
        index = [
            {"docId": "docA", "backupPath": "x.kmind", "operation": "add-node",
             "createdAt": datetime.now(timezone.utc).isoformat(),
             "sha256Before": "s", "sizeBytes": 5, "source": "assets/x.kmind"},
        ]
        # An unrelated doc -> empty list, no error.
        assert K.list_kmind_backups(backup_dir, index, "docB")["summary"]["count"] == 0
        # The matching doc -> one entry, present on disk.
        out_a = K.list_kmind_backups(backup_dir, index, "docA")
        assert [b["backupPath"] for b in out_a["backups"]] == ["x.kmind"]
        assert out_a["backups"][0]["existsOnDisk"] is True
        assert out_a["summary"]["missingFiles"] == 0


def test_list_kmind_backups_reads_what_write_backup_wrote() -> None:
    """End-to-end: the lister must read back exactly what write_backup recorded."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        asset = data_dir / "assets" / "map.kmind"
        asset.parent.mkdir()
        asset.write_bytes(b'{"root":{"data":{"text":"<p>x</p>"},"children":[]}}')
        name = K.write_backup(
            data_dir=data_dir, asset_abs=asset, asset_rel="assets/map.kmind",
            doc_id="docZ", operation="add-node", sha256_before="shaZ",
            size_bytes=asset.stat().st_size, timestamp="20260601-120000-000000",
        )
        backup_dir = data_dir.joinpath(*K.BACKUP_REL_DIR)
        out = K.list_kmind_backups(backup_dir, K._load_backup_index(backup_dir), "docZ")
        assert out["summary"]["count"] == 1 and out["summary"]["missingFiles"] == 0
        assert out["summary"]["totalSizeBytes"] == asset.stat().st_size
        entry = out["backups"][0]
        assert entry["backupPath"] == name
        assert entry["operation"] == "add-node"
        assert entry["sha256Before"] == "shaZ"
        assert entry["source"] == "assets/map.kmind"
        assert entry["existsOnDisk"] is True


def test_list_kmind_backups_path_escape_counts_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        backup_dir = root / "backups"
        backup_dir.mkdir()
        (root / "outside.kmind").write_bytes(b"{}")
        index = [{"docId": "docX", "backupPath": "../outside.kmind",
                  "createdAt": datetime.now(timezone.utc).isoformat(),
                  "operation": "add-node", "sha256Before": "sha",
                  "sizeBytes": 2, "source": "assets/map.kmind"}]

        out = K.list_kmind_backups(backup_dir, index, "docX")

        assert out["summary"]["count"] == 1
        assert out["summary"]["missingFiles"] == 1
        assert out["backups"][0]["backupPath"] == "../outside.kmind"
        assert out["backups"][0]["existsOnDisk"] is False


# --- P3: siyuan_kmind_restore_backup (write, dry-run-first) -----------------
#
# Offline: resolve_restore_source + restore_kmind_backup operate on a given
# backup dir + index + asset path, so the whole write path (identity resolution,
# foreign-doc refusal, dry-run, before-restore backup, byte-for-byte restore,
# sha guard) is exercised without live SiYuan. The siyuan_kmind_restore_backup
# tool only adds doc resolution on top.


def test_resolve_restore_source_requires_exactly_one_identity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        for kwargs in ({}, {"backup_path": "b.kmind", "sha256_before": "s"}):
            try:
                K.resolve_restore_source(backup_dir, [], "docA", **kwargs)
                raise AssertionError(f"expected ValueError for {kwargs}")
            except ValueError:
                pass


def test_resolve_restore_source_by_path_and_by_sha() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        sha = _write_kmind(backup_dir / "g.kmind", _sample_tree())
        index = [{"docId": "docA", "backupPath": "g.kmind", "operation": "add-node",
                  "createdAt": "2026-06-01T00:00:00+00:00", "sha256Before": sha,
                  "sizeBytes": 1, "source": "assets/x.kmind"}]
        for src in (
            K.resolve_restore_source(backup_dir, index, "docA", backup_path="g.kmind"),
            K.resolve_restore_source(backup_dir, index, "docA", sha256_before=sha),
        ):
            assert src["backupSha256"] == sha
            assert src["entry"]["backupPath"] == "g.kmind"
            assert src["entry"]["docId"] == "docA"
            assert K.node_plain_text(src["backupRoot"]) == "论文梳理"


def test_resolve_restore_source_rejects_foreign_doc() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        sha = _write_kmind(backup_dir / "g.kmind", _sample_tree())
        index = [{"docId": "docOTHER", "backupPath": "g.kmind", "operation": "add-node",
                  "createdAt": "2026-06-01T00:00:00+00:00", "sha256Before": sha,
                  "sizeBytes": 1, "source": "assets/x.kmind"}]
        try:
            K.resolve_restore_source(backup_dir, index, "docA", backup_path="g.kmind")
            raise AssertionError("expected ValueError for a foreign-doc backup")
        except ValueError as exc:
            assert "docA" in str(exc) or "document" in str(exc).lower()


def test_resolve_restore_source_missing_and_escaping() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        # Not recorded in the index.
        try:
            K.resolve_restore_source(backup_dir, [], "docA", backup_path="nope.kmind")
            raise AssertionError("expected ValueError for an unknown backup")
        except ValueError:
            pass
        # Recorded but the file is gone from disk.
        gone = [{"docId": "docA", "backupPath": "gone.kmind", "operation": "add-node",
                 "createdAt": "t", "sha256Before": "s", "sizeBytes": 1, "source": "x"}]
        try:
            K.resolve_restore_source(backup_dir, gone, "docA", backup_path="gone.kmind")
            raise AssertionError("expected FileNotFoundError for a missing backup file")
        except FileNotFoundError:
            pass
        # A corrupt index entry whose path escapes the backup dir is rejected.
        escaping = [{"docId": "docA", "backupPath": "../evil.kmind", "operation": "add-node",
                     "createdAt": "t", "sha256Before": "esc", "sizeBytes": 1, "source": "x"}]
        try:
            K.resolve_restore_source(backup_dir, escaping, "docA", sha256_before="esc")
            raise AssertionError("expected ValueError for an escaping backup path")
        except ValueError:
            pass


def _restore_fixture(tmp: str) -> tuple[Path, Path, str, list[dict]]:
    """data_dir with a good docA backup on disk + index, and a different current asset."""
    data_dir = Path(tmp)
    backup_dir = data_dir.joinpath(*K.BACKUP_REL_DIR)
    backup_dir.mkdir(parents=True)
    (data_dir / "assets").mkdir()

    good_sha = _write_kmind(backup_dir / "good.kmind", _sample_tree())
    index = [{
        "source": "assets/map.kmind", "docId": "docA", "backupPath": "good.kmind",
        "operation": "add-node", "createdAt": "2026-06-01T00:00:00+00:00",
        "sha256Before": good_sha, "sizeBytes": (backup_dir / "good.kmind").stat().st_size,
    }]
    K._save_backup_index(backup_dir, index)

    cur_tree = _sample_tree()
    cur_tree["root"]["data"]["text"] = "<p>DAMAGED</p>"
    asset = data_dir / "assets" / "map.kmind"
    _write_kmind(asset, cur_tree)
    return data_dir, asset, good_sha, index


def test_restore_kmind_backup_dry_run_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, asset, good_sha, index = _restore_fixture(tmp)
        backup_dir = data_dir.joinpath(*K.BACKUP_REL_DIR)
        before_files = sorted(p.name for p in backup_dir.iterdir())
        cur_bytes = asset.read_bytes()
        cur_sha = K._sha256(cur_bytes)

        out = K.restore_kmind_backup(
            asset_abs=asset, data_dir=data_dir, asset_rel="assets/map.kmind",
            doc_id="docA", index=index, sha256_before=good_sha, dry_run=True,
        )

        assert out["dryRun"] is True and out["backupCreated"] is None
        assert out["current"]["sha256"] == cur_sha
        assert out["willRestoreToSha256"] == good_sha
        assert out["backup"]["backupPath"] == "good.kmind"
        assert out["backup"]["backupSha256"] == good_sha
        assert isinstance(out["diffSummary"], dict) and out["diffSummary"]["changed"] >= 1
        assert "hint" in out
        # Disk is untouched: same asset bytes, no new backup files.
        assert asset.read_bytes() == cur_bytes
        assert sorted(p.name for p in backup_dir.iterdir()) == before_files


def test_restore_kmind_backup_real_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, asset, good_sha, index = _restore_fixture(tmp)
        backup_dir = data_dir.joinpath(*K.BACKUP_REL_DIR)
        cur_sha = K._sha256(asset.read_bytes())
        assert cur_sha != good_sha

        out = K.restore_kmind_backup(
            asset_abs=asset, data_dir=data_dir, asset_rel="assets/map.kmind",
            doc_id="docA", index=index, backup_path="good.kmind", dry_run=False,
        )

        # Restored byte-for-byte to the backup.
        assert out["dryRun"] is False
        assert out["sha256After"] == good_sha
        assert asset.read_bytes() == (backup_dir / "good.kmind").read_bytes()
        assert K.node_plain_text(K._require_root(K.load_kmind(asset)[0])) == "论文梳理"

        # A before-restore backup of the prior (damaged) content was created...
        created = out["backupCreated"]
        assert created and "before-restore" in created
        assert K._sha256((backup_dir / created).read_bytes()) == cur_sha
        # ...and recorded in the index for docA with operation "restore".
        disk_index = json.loads((backup_dir / K.BACKUP_INDEX_NAME).read_text())
        assert any(
            e["backupPath"] == created and e["docId"] == "docA"
            and e["operation"] == "restore" and e["sha256Before"] == cur_sha
            for e in disk_index
        )


def test_restore_kmind_backup_expected_sha_mismatch_aborts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, asset, good_sha, index = _restore_fixture(tmp)
        backup_dir = data_dir.joinpath(*K.BACKUP_REL_DIR)
        before_files = sorted(p.name for p in backup_dir.iterdir())
        cur_bytes = asset.read_bytes()

        try:
            K.restore_kmind_backup(
                asset_abs=asset, data_dir=data_dir, asset_rel="assets/map.kmind",
                doc_id="docA", index=index, backup_path="good.kmind",
                expected_sha256="not-the-current-sha", dry_run=False,
            )
            raise AssertionError("expected ValueError for an expected_sha256 mismatch")
        except ValueError:
            pass
        # Aborted before any write: asset unchanged, no before-restore backup made.
        assert asset.read_bytes() == cur_bytes
        assert sorted(p.name for p in backup_dir.iterdir()) == before_files


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
