"""Offline KMind storage regression tests."""

from __future__ import annotations
import json
import multiprocessing
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from siyuan_mcp import kmind as K
from siyuan_mcp import kmind_backups as B
from siyuan_mcp import kmind_storage as F


def _write_backup_worker(data_dir: str, asset_name: str, ready, start) -> None:
    asset = Path(data_dir) / asset_name
    raw = asset.read_bytes()
    ready.put(True)
    start.wait(10)
    for sequence in range(8):
        B.write_backup(Path(data_dir), asset, asset_name, asset_name,
                       "edit", F.sha256_bytes(raw), len(raw),
                       f"20260929-120000-{sequence:06d}", raw)


def test_dump_is_compact_and_roundtrips() -> None:
    data = {"root": {"data": {"text": "<p>中文</p>", "uid": "u"}, "children": []}}
    raw = F.dump_kmind_bytes(data)
    assert b" " not in raw  # compact (no spaces between tokens)
    assert "中文".encode("utf-8") in raw  # not ascii-escaped
    assert json.loads(raw.decode("utf-8")) == data


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
        kept = B.cleanup_kmind_backups(backup_dir, index)
        assert len(kept) == B.MAX_BACKUPS_PER_DOC == 20
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
        kept = B.cleanup_kmind_backups(backup_dir, index)
        assert [e["backupPath"] for e in kept] == ["new.kmind"]
        assert not old.exists() and new.exists()


def test_cleanup_rejects_paths_outside_backup_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        backups = root / "backups"
        backups.mkdir()
        victim = root / "victim.kmind"
        victim.write_bytes(b"keep")
        (backups / B.BACKUP_INDEX_NAME).write_text("[]")
        (backups / (B.BACKUP_INDEX_NAME + ".mcp.lock")).write_bytes(b"lock")
        for bad in ("../victim.kmind", str(victim), "", ".",
                    B.BACKUP_INDEX_NAME, B.BACKUP_INDEX_NAME + ".mcp.lock"):
            entries = [{"docId": "d", "backupPath": bad, "sizeBytes": 4,
                        "createdAt": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()}]
            assert B.cleanup_kmind_backups(backups, entries) == []
            assert victim.read_bytes() == b"keep"
            assert (backups / B.BACKUP_INDEX_NAME).read_text() == "[]"
            assert (backups / (B.BACKUP_INDEX_NAME + ".mcp.lock")).read_bytes() == b"lock"


def test_cleanup_does_not_follow_backup_symlink() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        backups = root / "backups"
        backups.mkdir()
        victim = root / "victim.kmind"
        victim.write_bytes(b"keep")
        link = backups / "linked.kmind"
        try:
            link.symlink_to(victim)
        except (OSError, NotImplementedError):
            raise unittest.SkipTest("symlink creation is unavailable")
        entry = {"docId": "d", "backupPath": "linked.kmind", "sizeBytes": 4,
                 "createdAt": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()}
        assert B.cleanup_kmind_backups(backups, [entry]) == []
        assert link.is_symlink() and victim.read_bytes() == b"keep"


def test_edit_during_backup_aborts_without_overwrite() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        asset = root / "map.kmind"
        original = {"root": {"data": {"text": "original"}, "children": []}}
        asset.write_bytes(F.dump_kmind_bytes(original))
        before = F.sha256_bytes(asset.read_bytes())
        ui_bytes = F.dump_kmind_bytes({"root": {"data": {"text": "UI edit"}, "children": []}})
        meta = {"assetAbsPath": str(asset), "assetRelPath": "assets/map.kmind", "docId": "fixture"}

        def during_backup(**_kwargs):
            asset.write_bytes(ui_bytes)
            return "fixture-backup.kmind"

        def mutate(data):
            data["root"]["data"]["text"] = "MCP edit"
            return {}

        with mock.patch.object(K, "find_siyuan_data_dir", return_value=root), \
                mock.patch.object(K, "write_backup", side_effect=during_backup):
            try:
                K._write_with_guard(meta, "edit", mutate, before, True, False)
                raise AssertionError("concurrent edit must abort")
            except ValueError as error:
                assert "changed on disk" in str(error)
        assert asset.read_bytes() == ui_bytes


def test_parallel_process_backups_preserve_index_entries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("first.kmind", "second.kmind"):
            (root / name).write_bytes(b"fixture")
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Queue()
        start = ctx.Event()
        workers = [ctx.Process(target=_write_backup_worker,
                               args=(tmp, name, ready, start))
                   for name in ("first.kmind", "second.kmind")]
        for worker in workers:
            worker.start()
        try:
            for _ in workers:
                assert ready.get(timeout=15)
            start.set()
            for worker in workers:
                worker.join(30)
                assert worker.exitcode == 0
        finally:
            start.set()
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
        backup_dir = B.get_backup_dir(root)
        entries = B._load_backup_index(backup_dir)
        assert len(entries) == 16
        assert {entry["docId"] for entry in entries} == {"first.kmind", "second.kmind"}
        assert all((backup_dir / entry["backupPath"]).read_bytes() == b"fixture"
                   for entry in entries)


def test_corrupt_index_aborts_without_overwrite() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        asset = root / "map.kmind"
        asset.write_bytes(b"fixture")
        backup_dir = B.get_backup_dir(root)
        backup_dir.mkdir(parents=True)
        index_path = backup_dir / B.BACKUP_INDEX_NAME
        index_path.write_text("corrupt", encoding="utf-8")
        try:
            B.write_backup(root, asset, "map.kmind", "doc", "edit",
                           F.sha256_bytes(b"fixture"), 7, "20260929-120000")
            raise AssertionError("corrupt index must fail")
        except ValueError as error:
            assert "Invalid KMind backup index" in str(error)
        assert index_path.read_text(encoding="utf-8") == "corrupt"
        assert sorted(path.suffix for path in backup_dir.glob("*.kmind")) == []


def test_backup_rejects_mismatched_hash_or_size() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        asset = root / "map.kmind"
        asset.write_bytes(b"fixture")
        for sha, size in (("wrong", 7), (F.sha256_bytes(b"fixture"), 8)):
            try:
                B.write_backup(root, asset, "map.kmind", "doc", "edit",
                               sha, size, "20260929-120000")
                raise AssertionError("mismatched backup metadata must fail")
            except ValueError as error:
                assert "do not match" in str(error)
        backup_dir = B.get_backup_dir(root)
        assert not list(backup_dir.glob("*.kmind"))


def test_atomic_replace_failure_keeps_original_and_removes_temp() -> None:
    from siyuan_mcp import kmind_storage

    with tempfile.TemporaryDirectory() as tmp:
        asset = Path(tmp) / "map.kmind"
        asset.write_bytes(b"original")
        with mock.patch.object(kmind_storage.os, "replace", side_effect=OSError("failed")):
            try:
                kmind_storage.atomic_replace(asset, b"new")
                raise AssertionError("replace failure expected")
            except OSError:
                pass
        assert asset.read_bytes() == b"original"
        assert sorted(path.name for path in Path(tmp).iterdir()) == ["map.kmind"]


def test_ui_edit_during_temp_file_fsync_aborts_commit() -> None:
    from siyuan_mcp import kmind_storage

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        asset = root / "map.kmind"
        asset.write_bytes(b"original")
        ui_bytes = b"external UI edit"
        original_fsync = kmind_storage.os.fsync

        def edit_during_fsync(fd):
            original_fsync(fd)
            asset.write_bytes(ui_bytes)

        with mock.patch.object(kmind_storage.os, "fsync", side_effect=edit_during_fsync):
            try:
                kmind_storage.commit_asset(asset, F.sha256_bytes(b"original"), b"MCP edit",
                                            F.sha256_bytes, lambda _current: None)
                raise AssertionError("UI edit must abort commit")
            except ValueError as error:
                assert "changed on disk" in str(error)
        assert asset.read_bytes() == ui_bytes
        assert not list(root.glob(".map.kmind.*.tmp"))


def test_backup_same_second_collision_keeps_both_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        asset = data_dir / "assets" / "map.kmind"
        asset.parent.mkdir()
        asset.write_bytes(b'{"root":{"data":{"text":"<p>x</p>"},"children":[]}}')

        first = B.write_backup(
            data_dir=data_dir,
            asset_abs=asset,
            asset_rel="assets/map.kmind",
            doc_id="doc1",
            operation="add-node",
            sha256_before=F.sha256_bytes(asset.read_bytes()),
            size_bytes=asset.stat().st_size,
            timestamp="20260601-120000-000000",
        )
        second = B.write_backup(
            data_dir=data_dir,
            asset_abs=asset,
            asset_rel="assets/map.kmind",
            doc_id="doc1",
            operation="add-node",
            sha256_before=F.sha256_bytes(asset.read_bytes()),
            size_bytes=asset.stat().st_size,
            timestamp="20260601-120000-000000",
        )

        backup_dir = data_dir.joinpath(*B.BACKUP_REL_DIR)
        assert first != second
        assert (backup_dir / first).exists()
        assert (backup_dir / second).exists()
        index = json.loads((backup_dir / B.BACKUP_INDEX_NAME).read_text())
        assert [entry["backupPath"] for entry in index] == [first, second]


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
