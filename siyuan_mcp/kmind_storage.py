"""KMind serialization and best-effort serialized, atomic file commits.

The sidecar lock coordinates MCP processes only. SiYuan UI does not take it,
so hash checks detect external edits but cannot provide a true CAS.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_kmind(asset_abs: str | Path) -> tuple[dict[str, Any], str, int]:
    raw = Path(asset_abs).read_bytes()
    return json.loads(raw.decode("utf-8")), _sha256(raw), len(raw)


def dump_kmind_bytes(data: dict[str, Any]) -> bytes:
    # KMind writes compact JSON (no whitespace); match it to avoid reformat churn.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


_thread_lock = threading.RLock()


@contextmanager
def file_lock(path: Path):
    """Serialize cooperating MCP processes; callers lock asset before index."""
    lock_path = path.with_name(path.name + ".mcp.lock")
    with _thread_lock, lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_replace(
    path: Path, data: bytes, *, before_replace: Callable[[], object] | None = None,
) -> None:
    """Replace a file without exposing a partially written destination."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode)
        if before_replace is not None:
            before_replace()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def commit_asset(
    asset: Path,
    expected_sha: str,
    replacement: bytes,
    sha256: Callable[[bytes], str],
    backup: Callable[[bytes], str | None],
) -> str | None:
    """Commit under the MCP lock, checking both sides of backup IO."""
    def verify() -> bytes:
        current = asset.read_bytes()
        if sha256(current) != expected_sha:
            raise ValueError(
                "KMind file changed on disk during processing; aborting to avoid "
                "overwriting a concurrent edit. Re-read and retry."
            )
        return current

    with file_lock(asset):
        current = verify()
        backup_name = backup(current)
        atomic_replace(asset, replacement, before_replace=verify)
        return backup_name
