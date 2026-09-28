from __future__ import annotations

import json
import re
from pathlib import Path

from siyuan_mcp import __version__
from siyuan_mcp.core import VERSION


def pyproject_version() -> str:
    root = Path(__file__).resolve().parents[1]
    in_project_section = False
    version_re = re.compile(r"""^version\s*=\s*["']([^"']+)["']\s*$""")
    for raw_line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project_section = line == "[project]"
            continue
        if not in_project_section:
            continue
        match = version_re.match(line)
        if match:
            return match.group(1)
    raise AssertionError("pyproject.toml has no [project] version")


def test_runtime_versions_match_pyproject() -> None:
    expected = pyproject_version()
    assert __version__ == expected
    assert VERSION == expected


def test_plugin_manifest_versions_match_pyproject() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = pyproject_version()
    manifest_paths = [
        root / ".claude-plugin" / "marketplace.json",
        root / "plugins" / "siyuan-mcp" / ".claude-plugin" / "plugin.json",
        root / "plugins" / "siyuan-mcp" / ".codex-plugin" / "plugin.json",
    ]
    for path in manifest_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "marketplace.json":
            versions = [plugin.get("version") for plugin in data.get("plugins", [])]
            assert expected in versions, f"{path} does not list version {expected}: {versions}"
        else:
            assert data.get("version") == expected, f"{path} version drifted from pyproject"


def test_lock_and_plugin_kmind_config_match_release() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = pyproject_version()
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    package = lock.split('name = "siyuan-mcp"', 1)[1].split("[[package]]", 1)[0]
    assert f'version = "{expected}"' in package

    plugin = root / "plugins" / "siyuan-mcp"
    claude = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude_mcp = json.loads((plugin / "claude.mcp.json").read_text(encoding="utf-8"))
    codex_mcp = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))
    assert "siyuan_data_dir" in claude["userConfig"]
    assert claude_mcp["mcpServers"]["siyuan"]["env"]["SIYUAN_DATA_DIR"] == "${user_config.siyuan_data_dir}"
    assert "SIYUAN_DATA_DIR" in codex_mcp["mcpServers"]["siyuan"]["env_vars"]


def main() -> None:
    test_runtime_versions_match_pyproject()
    test_plugin_manifest_versions_match_pyproject()
    print("\n2 passed")


if __name__ == "__main__":
    main()
