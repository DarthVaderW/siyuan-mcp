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


def main() -> None:
    test_runtime_versions_match_pyproject()
    test_plugin_manifest_versions_match_pyproject()
    print("\n2 passed")


if __name__ == "__main__":
    main()
