"""Offline KMind resolution regression tests."""

from __future__ import annotations
import tempfile
from unittest import mock
from pathlib import Path
from siyuan_mcp import kmind as K
from siyuan_mcp import core as C


def test_data_dir_explicit_override_without_config_disclosure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(K.os.environ, {"SIYUAN_DATA_DIR": tmp}):
            with mock.patch.object(K, "call_siyuan", side_effect=AssertionError("no API needed")):
                assert K.find_siyuan_data_dir() == Path(tmp).resolve()


def test_data_dir_rejects_relative_override() -> None:
    with mock.patch.dict(K.os.environ, {"SIYUAN_DATA_DIR": "relative/data"}):
        try:
            K.find_siyuan_data_dir()
            raise AssertionError("relative override must fail")
        except ValueError as error:
            assert "absolute" in str(error)


def test_data_dir_redacted_config_has_actionable_error() -> None:
    with mock.patch.dict(K.os.environ, {"SIYUAN_DATA_DIR": ""}):
        with mock.patch.object(K, "call_siyuan", return_value={"conf": {"system": {"dataDir": "", "workspaceDir": ""}}}):
            try:
                K.find_siyuan_data_dir()
                raise AssertionError("redacted config must fail")
            except RuntimeError as error:
                assert "SIYUAN_DATA_DIR" in str(error)


def test_data_dir_legacy_config_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(K.os.environ, {"SIYUAN_DATA_DIR": ""}):
            with mock.patch.object(K, "call_siyuan", return_value={"conf": {"system": {"dataDir": tmp}}}):
                assert K.find_siyuan_data_dir() == Path(tmp)


def test_kmind_resolution_reuses_core_id_fast_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "assets").mkdir()
        (root / "assets" / "map.kmind").write_bytes(b"{}")
        notebook_id = "20260929000000-abcdefg"
        calls = []

        def core_api(endpoint, payload):
            calls.append(endpoint)
            if endpoint == "/api/filetree/getIDsByHPath":
                assert payload == {"notebook": notebook_id, "path": "/Map"}
                return ["doc-id"]
            if endpoint == "/api/filetree/getHPathByID":
                return "/Map"
            raise AssertionError(f"unexpected core call: {endpoint}")

        with mock.patch.object(C, "call_siyuan", side_effect=core_api), \
                mock.patch.object(K, "call_siyuan", return_value={K.DOC_KMIND_ASSET_ATTR: "assets/map.kmind"}), \
                mock.patch.object(K, "find_siyuan_data_dir", return_value=root):
            result = K.resolve_kmind_doc(path="Map", notebook=notebook_id)
        assert result["docId"] == "doc-id"
        assert calls == ["/api/filetree/getIDsByHPath", "/api/filetree/getHPathByID"]


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    main()
