#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export TMPDIR="${ROOT}/.tmp"
export UV_CACHE_DIR="${ROOT}/.uv-cache"
mkdir -p "$TMPDIR" "$UV_CACHE_DIR"

cd "$ROOT"
exec uv run python -m siyuan_mcp.server \
  --transport streamable-http \
  --host "${SIYUAN_MCP_HOST:-127.0.0.1}" \
  --port "${SIYUAN_MCP_PORT:-6816}" \
  --path "${SIYUAN_MCP_PATH:-/mcp}"
