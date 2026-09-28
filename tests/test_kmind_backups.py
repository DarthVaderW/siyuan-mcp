"""Offline KMind backups regression tests."""

from __future__ import annotations
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from siyuan_mcp import kmind_tree as T
from siyuan_mcp import kmind_backups as B
from siyuan_mcp import kmind_storage as F
from kmind_fixtures import _sample_tree, _write_kmind


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
        ref = B.resolve_diff_reference(backup_dir, index, "docX")
        assert ref["status"] == "ok"
        # Picked the newest by createdAt, not by file/index order, and reported it.
        report = ref["reference"]
        assert report["kind"] == "latest-backup"
        assert report["backupPath"] == "new.kmind"
        assert report["createdAt"] == index[1]["createdAt"]
        assert report["sha256Before"] == new_sha and report["sha256"] == new_sha
        assert report["backupStore"] is None
        assert Path(report["backupDir"]).resolve() == backup_dir.resolve()
        assert T.node_plain_text(ref["root"]) == "MARKER"


def test_resolve_diff_reference_no_reference_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ref = B.resolve_diff_reference(Path(tmp), [], "docX")
        assert ref["status"] == "no-reference-available"
        assert ref["root"] is None and ref["reference"] is None
        assert "backup" in ref["message"].lower()


def test_resolve_diff_reference_explicit_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ref_file = Path(tmp) / "other.kmind"
        sha = _write_kmind(ref_file, _sample_tree())
        ref = B.resolve_diff_reference(Path(tmp), [], "docX", against_file=str(ref_file))
        assert ref["status"] == "ok"
        assert ref["reference"] == {
            "kind": "file", "filePath": str(ref_file), "sha256": sha, "sizeBytes": ref_file.stat().st_size,
        }
        assert T.node_uid(ref["root"]) == "u-root"


def test_resolve_diff_reference_by_sha() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        sha = _write_kmind(backup_dir / "b.kmind", _sample_tree())
        index = [{"docId": "docX", "backupPath": "b.kmind", "operation": "add-node",
                  "createdAt": datetime.now(timezone.utc).isoformat(), "sha256Before": sha, "sizeBytes": 1}]
        ref = B.resolve_diff_reference(backup_dir, index, "docX", against_sha256=sha)
        assert ref["status"] == "ok" and ref["reference"]["kind"] == "sha256"
        assert ref["reference"]["sha256Before"] == sha
        # Unknown sha must error, not silently fall back.
        try:
            B.resolve_diff_reference(backup_dir, index, "docX", against_sha256="deadbeef")
            raise AssertionError("expected ValueError for unknown sha256")
        except ValueError:
            pass


def test_resolve_diff_reference_by_backup_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        _write_kmind(backup_dir / "b.kmind", _sample_tree())
        index = [{"docId": "docX", "backupPath": "b.kmind", "operation": "add-node",
                  "createdAt": datetime.now(timezone.utc).isoformat(), "sha256Before": "x", "sizeBytes": 1}]
        ref = B.resolve_diff_reference(backup_dir, index, "docX", against_backup_path="b.kmind")
        assert ref["status"] == "ok" and ref["reference"]["kind"] == "backup-path"
        assert ref["reference"]["backupPath"] == "b.kmind"
        assert ref["reference"]["operation"] == "add-node"
        # Missing backup file must raise, not silently diff against nothing.
        try:
            B.resolve_diff_reference(backup_dir, index, "docX", against_backup_path="missing.kmind")
            raise AssertionError("expected FileNotFoundError for missing backup")
        except FileNotFoundError:
            pass


def test_resolve_diff_reference_rejects_multiple_refs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            B.resolve_diff_reference(
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

        ref = B.resolve_diff_reference(backup_dir, index, "docX")
        assert ref["status"] == "no-reference-available"
        assert "escapes backup dir" in ref["message"]

        try:
            B.resolve_diff_reference(backup_dir, index, "docX", against_sha256="sha-escape")
            raise AssertionError("expected ValueError for backup path escaping backup dir")
        except ValueError as error:
            assert "escapes backup dir" in str(error)


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
        out = B.list_kmind_backups(backup_dir, index, "docA")

        # Only docA, newest first (a2 is newer than a1).
        assert [b["backupPath"] for b in out["backups"]] == ["a2.kmind", "a1.kmind"]
        # The newest entry carries exactly the required fields; its file is gone.
        assert out["backups"][0] == {
            "backupPath": "a2.kmind", "createdAt": index[1]["createdAt"],
            "operation": "style-node", "sha256Before": "sha-a2", "sizeBytes": 20,
            "source": "assets/a.kmind", "backupStore": "current",
            "backupDir": str(backup_dir), "existsOnDisk": False,
        }
        assert out["backups"][1]["existsOnDisk"] is True
        # docB excluded; total = 10 + 20; a2's file missing -> missingFiles == 1.
        assert out["summary"] == {
            "count": 2, "totalSizeBytes": 30, "missingFiles": 1,
            "backupDir": str(backup_dir), "backupStores": ["current"],
        }


def test_list_kmind_backups_empty_is_not_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        out = B.list_kmind_backups(backup_dir, [], "docMissing")
        assert out["backups"] == []
        assert out["summary"] == {
            "count": 0, "totalSizeBytes": 0, "missingFiles": 0,
            "backupDir": str(backup_dir), "backupStores": [],
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
        assert B.list_kmind_backups(backup_dir, index, "docB")["summary"]["count"] == 0
        # The matching doc -> one entry, present on disk.
        out_a = B.list_kmind_backups(backup_dir, index, "docA")
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
        name = B.write_backup(
            data_dir=data_dir, asset_abs=asset, asset_rel="assets/map.kmind",
            doc_id="docZ", operation="add-node", sha256_before=F._sha256(asset.read_bytes()),
            size_bytes=asset.stat().st_size, timestamp="20260601-120000-000000",
        )
        backup_dir = data_dir.joinpath(*B.BACKUP_REL_DIR)
        out = B.list_kmind_backups(backup_dir, B._load_backup_index(backup_dir), "docZ")
        assert out["summary"]["count"] == 1 and out["summary"]["missingFiles"] == 0
        assert out["summary"]["totalSizeBytes"] == asset.stat().st_size
        entry = out["backups"][0]
        assert entry["backupPath"] == name
        assert entry["operation"] == "add-node"
        assert entry["sha256Before"] == F._sha256(asset.read_bytes())
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

        out = B.list_kmind_backups(backup_dir, index, "docX")

        assert out["summary"]["count"] == 1
        assert out["summary"]["missingFiles"] == 1
        assert out["backups"][0]["backupPath"] == "../outside.kmind"
        assert out["backups"][0]["existsOnDisk"] is False


def test_resolve_restore_source_requires_exactly_one_identity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        for kwargs in ({}, {"backup_path": "b.kmind", "sha256_before": "s"}):
            try:
                B.resolve_restore_source(backup_dir, [], "docA", **kwargs)
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
            B.resolve_restore_source(backup_dir, index, "docA", backup_path="g.kmind"),
            B.resolve_restore_source(backup_dir, index, "docA", sha256_before=sha),
        ):
            assert src["backupSha256"] == sha
            assert src["entry"]["backupPath"] == "g.kmind"
            assert src["entry"]["docId"] == "docA"
            assert T.node_plain_text(src["backupRoot"]) == "Example KMind"


def test_resolve_restore_source_rejects_foreign_doc() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        sha = _write_kmind(backup_dir / "g.kmind", _sample_tree())
        index = [{"docId": "docOTHER", "backupPath": "g.kmind", "operation": "add-node",
                  "createdAt": "2026-06-01T00:00:00+00:00", "sha256Before": sha,
                  "sizeBytes": 1, "source": "assets/x.kmind"}]
        try:
            B.resolve_restore_source(backup_dir, index, "docA", backup_path="g.kmind")
            raise AssertionError("expected ValueError for a foreign-doc backup")
        except ValueError as exc:
            assert "docA" in str(exc) or "document" in str(exc).lower()


def test_resolve_restore_source_missing_and_escaping() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        # Not recorded in the index.
        try:
            B.resolve_restore_source(backup_dir, [], "docA", backup_path="nope.kmind")
            raise AssertionError("expected ValueError for an unknown backup")
        except ValueError:
            pass
        # Recorded but the file is gone from disk.
        gone = [{"docId": "docA", "backupPath": "gone.kmind", "operation": "add-node",
                 "createdAt": "t", "sha256Before": "s", "sizeBytes": 1, "source": "x"}]
        try:
            B.resolve_restore_source(backup_dir, gone, "docA", backup_path="gone.kmind")
            raise AssertionError("expected FileNotFoundError for a missing backup file")
        except FileNotFoundError:
            pass
        # A corrupt index entry whose path escapes the backup dir is rejected.
        escaping = [{"docId": "docA", "backupPath": "../evil.kmind", "operation": "add-node",
                     "createdAt": "t", "sha256Before": "esc", "sizeBytes": 1, "source": "x"}]
        try:
            B.resolve_restore_source(backup_dir, escaping, "docA", sha256_before="esc")
            raise AssertionError("expected ValueError for an escaping backup path")
        except ValueError:
            pass


def test_resolve_restore_source_rejects_corrupt_backup_hash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        _write_kmind(backup_dir / "g.kmind", _sample_tree())
        index = [{"docId": "docA", "backupPath": "g.kmind", "operation": "add-node",
                  "createdAt": "2026-06-01T00:00:00+00:00",
                  "sha256Before": "not-the-file-sha", "sizeBytes": 1,
                  "source": "assets/x.kmind"}]

        try:
            B.resolve_restore_source(backup_dir, index, "docA", backup_path="g.kmind")
            raise AssertionError("expected ValueError for backup hash mismatch")
        except ValueError as error:
            assert "hash mismatch" in str(error)


def _restore_fixture(tmp: str) -> tuple[Path, Path, str, list[dict]]:
    """data_dir with a good docA backup on disk + index, and a different current asset."""
    data_dir = Path(tmp)
    backup_dir = data_dir.joinpath(*B.BACKUP_REL_DIR)
    backup_dir.mkdir(parents=True)
    (data_dir / "assets").mkdir()

    good_sha = _write_kmind(backup_dir / "good.kmind", _sample_tree())
    index = [{
        "source": "assets/map.kmind", "docId": "docA", "backupPath": "good.kmind",
        "operation": "add-node", "createdAt": datetime.now(timezone.utc).isoformat(),
        "sha256Before": good_sha, "sizeBytes": (backup_dir / "good.kmind").stat().st_size,
    }]
    B._save_backup_index(backup_dir, index)

    cur_tree = _sample_tree()
    cur_tree["root"]["data"]["text"] = "<p>DAMAGED</p>"
    asset = data_dir / "assets" / "map.kmind"
    _write_kmind(asset, cur_tree)
    return data_dir, asset, good_sha, index


def test_restore_kmind_backup_dry_run_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, asset, good_sha, index = _restore_fixture(tmp)
        backup_dir = data_dir.joinpath(*B.BACKUP_REL_DIR)
        before_files = sorted(p.name for p in backup_dir.iterdir())
        cur_bytes = asset.read_bytes()
        cur_sha = F._sha256(cur_bytes)

        out = B.restore_kmind_backup(
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
        backup_dir = data_dir.joinpath(*B.BACKUP_REL_DIR)
        cur_sha = F._sha256(asset.read_bytes())
        assert cur_sha != good_sha

        out = B.restore_kmind_backup(
            asset_abs=asset, data_dir=data_dir, asset_rel="assets/map.kmind",
            doc_id="docA", index=index, backup_path="good.kmind", dry_run=False,
        )

        # Restored byte-for-byte to the backup.
        assert out["dryRun"] is False
        assert out["sha256After"] == good_sha
        assert asset.read_bytes() == (backup_dir / "good.kmind").read_bytes()
        assert T.node_plain_text(T._require_root(F.load_kmind(asset)[0])) == "Example KMind"

        # A before-restore backup of the prior (damaged) content was created...
        created = out["backupCreated"]
        assert created and "before-restore" in created
        assert F._sha256((backup_dir / created).read_bytes()) == cur_sha
        # ...and recorded in the index for docA with operation "restore".
        disk_index = json.loads((backup_dir / B.BACKUP_INDEX_NAME).read_text())
        assert any(
            e["backupPath"] == created and e["docId"] == "docA"
            and e["operation"] == "restore" and e["sha256Before"] == cur_sha
            for e in disk_index
        )


def test_restore_kmind_backup_expected_sha_mismatch_aborts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, asset, good_sha, index = _restore_fixture(tmp)
        backup_dir = data_dir.joinpath(*B.BACKUP_REL_DIR)
        before_files = sorted(p.name for p in backup_dir.iterdir())
        cur_bytes = asset.read_bytes()

        try:
            B.restore_kmind_backup(
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
