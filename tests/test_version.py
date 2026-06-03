from __future__ import annotations

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


def main() -> None:
    test_runtime_versions_match_pyproject()
    print("\n1 passed")


if __name__ == "__main__":
    main()
