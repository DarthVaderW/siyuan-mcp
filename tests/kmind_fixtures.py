"""Small tree and file fixtures shared by KMind tests."""

from __future__ import annotations
from pathlib import Path
from siyuan_mcp import kmind_storage as F


def _sample_tree() -> dict:
    """A small KMind doc with several hand-styled branches (distinct lineColors)."""
    return {
        "root": {
            "data": {"text": "<p>Example KMind</p>", "uid": "u-root", "expand": True},
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


def _write_kmind(path: Path, tree: dict) -> str:
    """Write a tree as a compact .kmind file; return its sha256 (as backups store)."""
    raw = F.dump_kmind_bytes(tree)
    path.write_bytes(raw)
    return F.sha256_bytes(raw)
