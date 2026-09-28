"""Offline KMind tree regression tests."""

from __future__ import annotations
import copy
import re
from siyuan_mcp import kmind_tree as T
from kmind_fixtures import _sample_tree


def test_html_text_and_rich_text() -> None:
    assert T.kmind_html_text("<p><span>基于运动学</span></p>") == "基于运动学"
    assert T.kmind_html_text("<p>a &amp; b</p>") == "a & b"
    assert T.kmind_html_text(None) == ""
    assert T.make_rich_text("hello") == "<p>hello</p>"
    assert T.make_rich_text("a & b") == "<p>a &amp; b</p>"


def test_uid_format() -> None:
    uid = T.generate_kmind_uid()
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
    assert T.count_nodes(root) == 4
    assert T.find_node_by_uid(root, "u-a1")["data"]["uid"] == "u-a1"
    assert T.find_node_by_uid(root, "missing") is None
    assert len(T.find_nodes_by_text(root, "a1")) == 1

    depths = {T.node_plain_text(n): d for n, d, _p in T.walk_kmind_nodes(root)}
    assert depths == {"root": 0, "a": 1, "a1": 2, "b": 1}

    outline = T.build_outline(root, max_depth=1, include_styles=False)
    assert [o["text"] for o in outline] == ["root", "a", "b"]
    assert T.build_outline_markdown(root, None) == "- root\n  - a\n    - a1\n  - b"


def test_apply_node_style_guards() -> None:
    data: dict = {}
    changed = T.apply_node_style(data, {"fillColor": "red", "fontSize": 14})
    assert set(changed) == {"fillColor", "fontSize"}
    assert data == {"fillColor": "red", "fontSize": 14}

    # lineColor is not a node style; must be rejected in node_style.
    try:
        T.apply_node_style({}, {"lineColor": "x"})
        raise AssertionError("expected ValueError for lineColor in node_style")
    except ValueError:
        pass

    # line_style accepts lineColor/lineWidth.
    d2: dict = {}
    T.apply_node_style(d2, {}, {"lineColor": "rgb(1,2,3)", "lineWidth": 2})
    assert d2 == {"lineColor": "rgb(1,2,3)", "lineWidth": 2}


def test_make_node() -> None:
    node = T.make_node("hi", {"color": "blue"})
    assert node["data"]["text"] == "<p>hi</p>"
    assert node["data"]["richText"] is True
    assert node["data"]["color"] == "blue"
    assert node["children"] == []
    assert re.match(r"^kmind-node-", node["data"]["uid"])


def _snapshot_data_by_uid(root: dict) -> dict:
    """{uid: deepcopy(node data)} for every node, for byte-for-byte comparison."""
    return {
        T.node_uid(n): copy.deepcopy(n.get("data", {}))
        for n, _d, _p in T.walk_kmind_nodes(root)
        if T.node_uid(n)
    }


def _assert_no_line_field_changes(root: dict, before: dict, exempt: set | None = None) -> None:
    """Assert no node's lineColor/lineWidth differs from `before` (except `exempt`).

    New nodes (uid absent from `before`) must carry no line fields at all.
    """
    exempt = exempt or set()
    for node, _d, _p in T.walk_kmind_nodes(root):
        uid = T.node_uid(node)
        if uid in exempt:
            continue
        data = node.get("data", {})
        if uid not in before:
            for field in T.LINE_STYLE_FIELDS:
                assert field not in data, f"new node {uid} gained line field {field!r}"
            continue
        prior = before[uid]
        for field in T.LINE_STYLE_FIELDS:
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
    root = T.require_root(data)
    before = _snapshot_data_by_uid(root)

    # Mirror siyuan_kmind_add_node's mutate(): locate parent, build the node
    # (with children), append under the parent. No existing node is touched.
    parent = T.locate_parent_node(root, "u-kin", None)
    new_node = T.make_node("微分运动学", {"fillColor": "rgb(200,200,200)"})
    for child_text in ["雅可比", "奇异性"]:
        new_node["children"].append(T.make_node(child_text))
    parent.setdefault("children", []).append(new_node)

    # (a) every pre-existing node's data is byte-for-byte identical.
    after = {T.node_uid(n): n.get("data", {}) for n, _d, _p in T.walk_kmind_nodes(root)}
    for uid, snapshot in before.items():
        assert after[uid] == snapshot, f"existing node {uid} data changed"

    # (b) no node anywhere gained/changed lineColor or lineWidth; the new node
    #     and its children are created unstyled (no line fields).
    _assert_no_line_field_changes(root, before)
    assert "lineColor" not in new_node["data"] and "lineWidth" not in new_node["data"]

    # The new node was appended last under the chosen parent and nothing else moved.
    assert T.node_uid(parent["children"][-1]) == T.node_uid(new_node)
    assert T.count_nodes(root) == len(before) + 3  # new node + its 2 children


def test_style_node_changes_only_declared_fields_on_target() -> None:
    """style_node (node_style only) must change only the target's declared fields."""
    data = _sample_tree()
    root = T.require_root(data)
    before = _snapshot_data_by_uid(root)
    target_uid = "u-dyn"

    # Mirror siyuan_kmind_style_node's mutate() with node_style only (no line_style).
    target = T.locate_target_node(root, target_uid, None)
    node_style = {"fillColor": "rgb(255,0,0)", "fontSize": 22}
    changed = T.apply_node_style(target["data"], node_style, None)
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
    root = T.require_root(data)
    before = _snapshot_data_by_uid(root)
    target_uid = "u-fk"  # currently yellow rgb(237,185,81)

    target = T.locate_target_node(root, target_uid, None)
    node_style = {"color": "rgb(10,20,30)"}
    line_style = {"lineColor": "rgb(0,0,255)", "lineWidth": 4}
    changed = T.apply_node_style(target["data"], node_style, line_style)
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


def test_classify_kmind_field() -> None:
    assert T.classify_kmind_field("text") == "content"
    assert T.classify_kmind_field("note") == "content"
    assert T.classify_kmind_field("fillColor") == "nodeStyle"
    assert T.classify_kmind_field("fontSize") == "nodeStyle"
    assert T.classify_kmind_field("lineColor") == "branchLine"
    assert T.classify_kmind_field("lineWidth") == "branchLine"
    assert T.classify_kmind_field("expand") == "other"
    assert T.classify_kmind_field("richText") == "other"


def test_diff_kmind_trees_identical_is_empty() -> None:
    tree = _sample_tree()
    diff = T.diff_kmind_trees(T.require_root(copy.deepcopy(tree)), T.require_root(tree))
    assert diff["added"] == [] and diff["removed"] == [] and diff["changed"] == []
    s = diff["summary"]
    assert (s["added"], s["removed"], s["changed"]) == (0, 0, 0)
    assert s["branchLineChanged"] is False and s["nodeStyleChanged"] is False
    assert s["fieldChangesByBucket"] == {"content": 0, "nodeStyle": 0, "branchLine": 0, "other": 0}


def test_diff_kmind_trees_added_removed_changed() -> None:
    ref_tree = _sample_tree()
    cur_tree = copy.deepcopy(ref_tree)
    cur_root = T.require_root(cur_tree)

    # changed: u-dyn text (content) + new fillColor (nodeStyle) + lineColor (branchLine)
    target = T.find_node_by_uid(cur_root, "u-dyn")
    target["data"]["text"] = "<p>动力学(改)</p>"
    target["data"]["fillColor"] = "rgb(1,2,3)"
    target["data"]["lineColor"] = "rgb(9,9,9)"
    # removed: leaf u-lag
    target["children"] = [c for c in target["children"] if T.node_uid(c) != "u-lag"]
    # added: a fresh child under u-kin
    new_node = T.make_node("新节点")
    T.find_node_by_uid(cur_root, "u-kin")["children"].append(new_node)

    diff = T.diff_kmind_trees(T.require_root(ref_tree), cur_root)

    assert [a["uid"] for a in diff["added"]] == [T.node_uid(new_node)]
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
    cur_root = T.require_root(cur_tree)
    T.find_node_by_uid(cur_root, "u-ik")["data"]["lineColor"] = None

    diff = T.diff_kmind_trees(T.require_root(ref_tree), cur_root)

    assert [c["uid"] for c in diff["changed"]] == ["u-ik"]
    ch = diff["changed"][0]
    assert ch["changedFields"]["branchLine"] == ["lineColor"]
    assert ch["values"]["lineColor"] == {
        "before": None, "after": None,
        "beforePresent": False, "afterPresent": True,
    }
    assert diff["summary"]["branchLineChanged"] is True


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
