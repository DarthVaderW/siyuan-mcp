"""KMind backup retention, index, reference selection and guarded restoration."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from siyuan_mcp.kmind_storage import sha256_bytes, atomic_replace, commit_asset, file_lock, load_kmind
from siyuan_mcp.kmind_tree import require_root, diff_kmind_trees


BACKUP_REL_DIR = ("storage", "siyuan-mcp-kmind-backups")


BACKUP_INDEX_NAME = "backup_index.json"


MAX_BACKUPS_PER_DOC = 20


MAX_BACKUP_AGE_DAYS = 30


MAX_BACKUP_TOTAL_BYTES = 100 * 1024 * 1024


def get_backup_dir(data_dir: Path) -> Path:
    return data_dir.joinpath(*BACKUP_REL_DIR)


def load_backup_view(data_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    backup_dir = get_backup_dir(data_dir)
    for entry in _load_backup_index(backup_dir):
        decorated = dict(entry)
        decorated["_backupStore"] = "current"
        decorated["_backupDir"] = str(backup_dir)
        entries.append(decorated)
    return entries


def _load_backup_index(backup_dir: Path) -> list[dict[str, Any]]:
    index_path = backup_dir / BACKUP_INDEX_NAME
    if not index_path.exists():
        return []
    try:
        loaded = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list) or not all(isinstance(entry, dict) for entry in loaded):
            raise ValueError(f"Invalid KMind backup index: {index_path}")
        return loaded
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid KMind backup index: {index_path}") from exc


def _save_backup_index(backup_dir: Path, index: list[dict[str, Any]]) -> None:
    atomic_replace(
        backup_dir / BACKUP_INDEX_NAME,
        json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def cleanup_kmind_backups(
    backup_dir: Path, index: list[dict[str, Any]], *, delete_files: bool = True,
) -> list[dict[str, Any]]:
    """Enforce per-doc count, age, and total-size limits. Oldest removed first."""
    kept = list(index)
    removed: list[dict[str, Any]] = []

    def drop(entry: dict[str, Any]) -> None:
        kept.remove(entry)
        removed.append(entry)
        target = _backup_path_in_dir(backup_dir, entry.get("backupPath"))
        if delete_files and target is not None and target.is_file():
            target.unlink()

    # Age limit.
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_BACKUP_AGE_DAYS)
    for entry in list(kept):
        created = entry.get("createdAt")
        try:
            ts = datetime.fromisoformat(created) if created else None
        except ValueError:
            ts = None
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                drop(entry)

    # Per-document count limit (oldest first).
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for entry in kept:
        by_doc.setdefault(entry.get("docId", ""), []).append(entry)
    for entries in by_doc.values():
        entries.sort(key=lambda e: e.get("createdAt", ""))
        while len(entries) > MAX_BACKUPS_PER_DOC:
            drop(entries.pop(0))

    # Total-size limit (oldest first across all docs).
    def total_size() -> int:
        return sum(int(e.get("sizeBytes") or 0) for e in kept)

    kept.sort(key=lambda e: e.get("createdAt", ""))
    age_ordered = list(kept)
    while total_size() > MAX_BACKUP_TOTAL_BYTES and age_ordered:
        drop(age_ordered.pop(0))

    return kept


def write_backup(
    data_dir: Path,
    asset_abs: Path,
    asset_rel: str,
    doc_id: str,
    operation: str,
    sha256_before: str,
    size_bytes: int,
    timestamp: str,
    raw_bytes: bytes | None = None,
) -> str:
    backup_dir = get_backup_dir(data_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    raw = asset_abs.read_bytes() if raw_bytes is None else raw_bytes
    if sha256_bytes(raw) != sha256_before or len(raw) != size_bytes:
        raise ValueError("KMind backup bytes do not match the recorded hash and size")
    # All index read/modify/write operations use this lock. Asset commits take
    # their asset lock first, then this shared index lock.
    with file_lock(backup_dir / BACKUP_INDEX_NAME):
        backup_name = f"{timestamp}__{doc_id}__before-{operation}.kmind"
        while (backup_dir / backup_name).exists():
            suffix = "".join(random.choice("0123456789abcdef") for _ in range(6))
            backup_name = f"{timestamp}__{doc_id}__before-{operation}-{suffix}.kmind"
        target = _backup_path_in_dir(backup_dir, backup_name)
        if target is None:
            raise ValueError("Invalid generated KMind backup path")
        atomic_replace(target, raw)
        try:
            previous = _load_backup_index(backup_dir)
            updated = previous + [{
                "source": asset_rel,
                "docId": doc_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "operation": operation,
                "sha256Before": sha256_before,
                "sizeBytes": size_bytes,
                "backupPath": backup_name,
            }]
            kept = cleanup_kmind_backups(backup_dir, updated, delete_files=False)
            _save_backup_index(backup_dir, kept)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        kept_paths = {entry.get("backupPath") for entry in kept}
        for entry in updated:
            if entry.get("backupPath") not in kept_paths:
                stale = _backup_path_in_dir(backup_dir, entry.get("backupPath"))
                if stale is not None and stale.is_file():
                    stale.unlink(missing_ok=True)
        return backup_name


def _backup_path_in_dir(backup_dir: Path, backup_path: str | None) -> Path | None:
    """Resolve a backup path only if it stays inside the backup directory."""
    if not isinstance(backup_path, str) or not backup_path.endswith(".kmind"):
        return None
    # Index records contain generated filenames, never absolute or nested paths.
    # Checking both separators also rejects Windows paths on POSIX.
    if "/" in backup_path or "\\" in backup_path or ":" in backup_path:
        return None
    base = backup_dir.resolve()
    raw_candidate = backup_dir / backup_path
    if raw_candidate.is_symlink():
        return None
    candidate = raw_candidate.resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate != base and not candidate.is_dir() else None


def _entry_backup_dir(default_backup_dir: Path, entry: dict[str, Any]) -> Path:
    backup_dir = entry.get("_backupDir")
    return Path(str(backup_dir)) if backup_dir else default_backup_dir


def _entry_backup_path(default_backup_dir: Path, entry: dict[str, Any]) -> Path | None:
    return _backup_path_in_dir(_entry_backup_dir(default_backup_dir, entry), entry.get("backupPath"))


def _candidate_backup_dirs(default_backup_dir: Path, index: list[dict[str, Any]]) -> list[Path]:
    dirs = [default_backup_dir]
    for entry in index:
        backup_dir = _entry_backup_dir(default_backup_dir, entry)
        if backup_dir not in dirs:
            dirs.append(backup_dir)
    return dirs


def _newest_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not entries:
        return None
    return max(entries, key=lambda e: (e.get("createdAt", ""), e.get("_backupStore", ""), e.get("backupPath", "")))


def list_kmind_backups(backup_dir: Path, index: list[dict[str, Any]], doc_id: str) -> dict[str, Any]:
    """Summarize the backups recorded for one document, newest first (read-only).

    Pure: operates on a given backup dir + index, so it needs no live SiYuan.
    Each backup reports backupPath / createdAt / operation / sha256Before /
    sizeBytes / source / existsOnDisk. The summary reports count, totalSizeBytes
    (sum of recorded sizeBytes across listed backups), missingFiles (entries whose
    file is gone from disk), and backupDir. A document with no backups yields an
    empty list and a zeroed summary — never an error.
    """
    backups: list[dict[str, Any]] = []
    missing_files = 0
    total_size = 0
    for entry in index:
        if entry.get("docId") != doc_id:
            continue
        backup_path = entry.get("backupPath")
        entry_backup_dir = _entry_backup_dir(backup_dir, entry)
        backup_abs = _entry_backup_path(backup_dir, entry)
        exists = backup_abs is not None and backup_abs.exists()
        if not exists:
            missing_files += 1
        total_size += int(entry.get("sizeBytes") or 0)
        backups.append(
            {
                "backupPath": backup_path,
                "createdAt": entry.get("createdAt"),
                "operation": entry.get("operation"),
                "sha256Before": entry.get("sha256Before"),
                "sizeBytes": entry.get("sizeBytes"),
                "source": entry.get("source"),
                "backupStore": entry.get("_backupStore") or "current",
                "backupDir": str(entry_backup_dir),
                "existsOnDisk": exists,
            }
        )
    backups.sort(key=lambda e: (e.get("createdAt") or "", e.get("backupPath") or ""), reverse=True)
    return {
        "backups": backups,
        "summary": {
            "count": len(backups),
            "totalSizeBytes": total_size,
            "missingFiles": missing_files,
            "backupDir": str(backup_dir),
            "backupStores": sorted({str(e.get("backupStore")) for e in backups}),
        },
    }


def load_kmind_root(asset_abs: str | Path) -> tuple[dict[str, Any], str, int]:
    data, sha256, size_bytes = load_kmind(asset_abs)
    return require_root(data), sha256, size_bytes


def _latest_backup_entry(index: list[dict[str, Any]], doc_id: str) -> dict[str, Any] | None:
    entries = [e for e in index if e.get("docId") == doc_id and e.get("backupPath")]
    if not entries:
        return None
    return max(entries, key=lambda e: e.get("createdAt", ""))


def _backup_reference_report(
    kind: str, entry: dict[str, Any] | None, ref_abs: Path, sha256: str, size_bytes: int
) -> dict[str, Any]:
    entry = entry or {}
    return {
        "kind": kind,
        "backupPath": entry.get("backupPath") or ref_abs.name,
        "createdAt": entry.get("createdAt"),
        "operation": entry.get("operation"),
        "sha256Before": entry.get("sha256Before"),
        "sha256": sha256,  # actual content sha of the reference we loaded
        "sizeBytes": size_bytes,
        "backupStore": entry.get("_backupStore"),
        "backupDir": entry.get("_backupDir") or str(ref_abs.parent),
    }


def resolve_diff_reference(
    backup_dir: Path,
    index: list[dict[str, Any]],
    doc_id: str,
    against_backup_path: str | None = None,
    against_sha256: str | None = None,
    against_file: str | None = None,
) -> dict[str, Any]:
    """Resolve the reference KMind tree for a diff (read-only).

    Precedence: at most one explicit reference (against_file / against_backup_path
    / against_sha256), else the latest backup for ``doc_id``. Returns
    ``{"status": "ok", "root": <root>, "reference": {...}}`` or, when nothing is
    available, ``{"status": "no-reference-available", "root": None,
    "reference": None, "message": ...}`` — it never silently diffs against
    nothing. The reference report always names the selected source.
    """
    explicit = [x for x in (against_backup_path, against_sha256, against_file) if x]
    if len(explicit) > 1:
        raise ValueError(
            "Provide at most one explicit reference: against_backup_path, "
            "against_sha256, or against_file."
        )

    if against_file:
        ref_abs = Path(against_file)
        if not ref_abs.exists():
            raise FileNotFoundError(f"Reference .kmind file not found: {against_file}")
        root, sha256, size_bytes = load_kmind_root(ref_abs)
        return {
            "status": "ok",
            "root": root,
            "reference": {
                "kind": "file",
                "filePath": str(ref_abs),
                "sha256": sha256,
                "sizeBytes": size_bytes,
            },
        }

    if against_backup_path:
        if _backup_path_in_dir(backup_dir, against_backup_path) is None:
            raise ValueError(f"Invalid backup path: {against_backup_path!r}")
        name = against_backup_path
        entry = _newest_entry([e for e in index if e.get("backupPath") == name])
        if entry:
            ref_abs = _entry_backup_path(backup_dir, entry)
            if ref_abs is None:
                raise ValueError(f"Backup path escapes backup dir: {against_backup_path}")
        else:
            ref_abs = next(
                (path for candidate in _candidate_backup_dirs(backup_dir, index)
                 if (path := _backup_path_in_dir(candidate, name)) is not None and path.is_file()),
                None,
            )
        if ref_abs is None or not ref_abs.exists():
            raise FileNotFoundError(f"Backup not found in backup stores: {against_backup_path}")
        root, sha256, size_bytes = load_kmind_root(ref_abs)
        return {
            "status": "ok",
            "root": root,
            "reference": _backup_reference_report("backup-path", entry, ref_abs, sha256, size_bytes),
        }

    if against_sha256:
        entry = next(
            (e for e in index if e.get("sha256Before") == against_sha256 and e.get("docId") == doc_id),
            None,
        )
        if not entry:
            raise ValueError(f"No backup with sha256Before={against_sha256} for document {doc_id}.")
        ref_abs = _entry_backup_path(backup_dir, entry)
        if ref_abs is None:
            raise ValueError(f"Backup path escapes backup dir: {entry.get('backupPath')}")
        if not ref_abs.exists():
            raise FileNotFoundError(f"Backup file missing on disk: {entry['backupPath']}")
        root, sha256, size_bytes = load_kmind_root(ref_abs)
        return {
            "status": "ok",
            "root": root,
            "reference": _backup_reference_report("sha256", entry, ref_abs, sha256, size_bytes),
        }

    entry = _latest_backup_entry(index, doc_id)
    if not entry:
        return {
            "status": "no-reference-available",
            "root": None,
            "reference": None,
            "message": (
                "No backup found for this document. Pass against_backup_path, "
                "against_sha256, or against_file to diff against an explicit reference."
            ),
        }
    ref_abs = _entry_backup_path(backup_dir, entry)
    if ref_abs is None:
        return {
            "status": "no-reference-available",
            "root": None,
            "reference": None,
            "message": f"Latest backup path escapes backup dir: {entry.get('backupPath')}.",
        }
    if not ref_abs.exists():
        return {
            "status": "no-reference-available",
            "root": None,
            "reference": None,
            "message": f"Latest backup file is missing on disk: {entry['backupPath']}.",
        }
    root, sha256, size_bytes = load_kmind_root(ref_abs)
    return {
        "status": "ok",
        "root": root,
        "reference": _backup_reference_report("latest-backup", entry, ref_abs, sha256, size_bytes),
    }


def resolve_restore_source(
    backup_dir: Path,
    index: list[dict[str, Any]],
    doc_id: str,
    backup_path: str | None = None,
    sha256_before: str | None = None,
) -> dict[str, Any]:
    """Resolve which backup to restore for ``doc_id`` (read-only resolution).

    Requires exactly one explicit identity — ``backup_path`` or ``sha256_before``;
    there is deliberately no "latest" default for a restore. The chosen backup
    MUST be recorded in the index for THIS document (its ``docId`` must match) and
    its file must stay inside the backup dir. Returns the loaded backup (raw bytes
    + validated root + sha) and its index entry. Raises ValueError /
    FileNotFoundError on any mismatch. No SiYuan calls.
    """
    provided = [x for x in (backup_path, sha256_before) if x]
    if len(provided) != 1:
        raise ValueError(
            "Provide exactly one backup identity: backup_path or sha256_before "
            "(restore has no 'latest' default)."
        )

    if backup_path:
        if _backup_path_in_dir(backup_dir, backup_path) is None:
            raise ValueError(f"Invalid backup path: {backup_path!r}")
        name = backup_path
        entry = _newest_entry([e for e in index if e.get("backupPath") == name])
        if not entry:
            raise ValueError(f"No backup named {name!r} recorded in the index.")
    else:
        entry = _newest_entry(
            [e for e in index if e.get("sha256Before") == sha256_before and e.get("docId") == doc_id]
        )
        if not entry:
            raise ValueError(
                f"No backup with sha256Before={sha256_before} recorded for document {doc_id}."
            )

    if entry.get("docId") != doc_id:
        raise ValueError(
            f"Refusing to restore: backup belongs to document {entry.get('docId')!r}, "
            f"not {doc_id!r}."
        )

    backup_abs = _entry_backup_path(backup_dir, entry)
    if backup_abs is None:
        raise ValueError(f"Backup path escapes backup dir: {entry.get('backupPath')!r}.")
    if not backup_abs.exists():
        raise FileNotFoundError(f"Backup file missing on disk: {entry.get('backupPath')!r}.")

    raw = backup_abs.read_bytes()
    backup_sha256 = sha256_bytes(raw)
    recorded_sha256 = entry.get("sha256Before")
    if recorded_sha256 and recorded_sha256 != backup_sha256:
        raise ValueError(
            f"Backup content hash mismatch for {entry.get('backupPath')!r}: "
            f"index records {recorded_sha256}, file is {backup_sha256}."
        )
    root = require_root(json.loads(raw.decode("utf-8")))  # validate restorable JSON + root
    return {
        "backupAbs": backup_abs,
        "backupRaw": raw,
        "backupRoot": root,
        "backupSha256": backup_sha256,
        "backupSizeBytes": len(raw),
        "entry": {
            "backupPath": entry.get("backupPath"),
            "createdAt": entry.get("createdAt"),
            "operation": entry.get("operation"),
            "sha256Before": entry.get("sha256Before"),
            "sizeBytes": entry.get("sizeBytes"),
            "source": entry.get("source"),
            "docId": entry.get("docId"),
            "backupStore": entry.get("_backupStore") or "current",
            "backupDir": str(_entry_backup_dir(backup_dir, entry)),
        },
    }


def restore_kmind_backup(
    *,
    asset_abs: Path,
    data_dir: Path,
    asset_rel: str,
    doc_id: str,
    index: list[dict[str, Any]],
    backup_path: str | None = None,
    sha256_before: str | None = None,
    expected_sha256: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Restore a KMind asset from one of its own backups, byte-for-byte.

    Offline-friendly: the caller does SiYuan resolution and passes paths + the
    backup index, so this needs no live SiYuan. ``dry_run`` (default True) writes
    nothing and creates no backup — it returns the chosen backup, current/backup
    sha, and a best-effort diff summary (current -> backup) so the change can be
    reviewed first. A real restore re-checks the on-disk sha to avoid clobbering a
    concurrent KMind UI edit, creates a ``before-restore`` backup of the current
    file, then writes the backup bytes back verbatim.
    """
    backup_dir = get_backup_dir(data_dir)
    src = resolve_restore_source(backup_dir, index, doc_id, backup_path, sha256_before)

    if not asset_abs.exists():
        raise FileNotFoundError(f"KMind asset not found on disk: {asset_abs}")
    cur_raw = asset_abs.read_bytes()
    cur_sha = sha256_bytes(cur_raw)
    if expected_sha256 and expected_sha256 != cur_sha:
        raise ValueError(
            f"sha256 mismatch for {doc_id}: expected {expected_sha256}, on-disk "
            f"{cur_sha}. Re-read the KMind file before restoring."
        )

    # Best-effort preview of what restoring would change (current -> backup).
    diff_summary: dict[str, Any] | None = None
    try:
        cur_root = require_root(json.loads(cur_raw.decode("utf-8")))
        diff_summary = diff_kmind_trees(cur_root, src["backupRoot"])["summary"]
    except (json.JSONDecodeError, ValueError):
        diff_summary = None

    result: dict[str, Any] = {
        "operation": "restore",
        "backup": {**src["entry"], "backupSha256": src["backupSha256"]},
        "current": {"sha256": cur_sha, "sizeBytes": len(cur_raw)},
        "willRestoreToSha256": src["backupSha256"],
        "identical": src["backupSha256"] == cur_sha,
        "diffSummary": diff_summary,
    }

    if dry_run:
        result["dryRun"] = True
        result["backupCreated"] = None
        result["hint"] = (
            "Preview only — nothing written. For full per-node detail run "
            "siyuan_kmind_diff against this backup, then re-call with dry_run=false "
            "to apply."
        )
        return result

    backup_created = commit_asset(
        asset_abs, cur_sha, src["backupRaw"], sha256_bytes,
        lambda current: write_backup(
            data_dir=data_dir,
            asset_abs=asset_abs,
            asset_rel=asset_rel,
            doc_id=doc_id,
            operation="restore",
            sha256_before=cur_sha,
            size_bytes=len(current),
            timestamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
            raw_bytes=current,
        ),
    )
    new_raw = asset_abs.read_bytes()
    result["dryRun"] = False
    result["backupCreated"] = backup_created
    result["sha256After"] = sha256_bytes(new_raw)
    result["sizeBytesAfter"] = len(new_raw)
    return result
