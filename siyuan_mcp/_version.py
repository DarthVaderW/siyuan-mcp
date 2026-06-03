"""Package version helpers."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


PACKAGE_NAME = "siyuan-mcp"
_VERSION_RE = re.compile(r"""^version\s*=\s*["']([^"']+)["']\s*$""")


def get_version() -> str:
    """Return the installed package version, falling back to local pyproject."""
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        pass

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    in_project_section = False
    try:
        for raw_line in pyproject.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                in_project_section = line == "[project]"
                continue
            if not in_project_section:
                continue
            match = _VERSION_RE.match(line)
            if match:
                return match.group(1)
    except OSError:
        pass

    return "0+unknown"
