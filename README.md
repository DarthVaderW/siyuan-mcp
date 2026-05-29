# SiYuan MCP

Pure SiYuan MCP server for the research system. This repository exposes
low-level SiYuan tools only: documents, blocks, search, attributes, and native
database/AttributeView operations.

It does not import PDFs, call Zotero, implement OpenClaw intake, or encode the
paper-system workflow. Those responsibilities live in sibling repositories.

## Install

This repository ships the same stdio MCP server for Codex and Claude Code. The
MCP implementation is shared; only the plugin shell differs by client.

Codex:

```bash
codex plugin marketplace add DarthVaderW/siyuan-mcp --ref stable \
  --sparse .agents/plugins \
  --sparse plugins/siyuan-mcp
codex plugin add siyuan-mcp@siyuan-mcp
```

Claude Code:

```text
/plugin marketplace add DarthVaderW/siyuan-mcp
/plugin install siyuan-mcp@darthvaderw-siyuan-mcp
```

## Configure

Required local values:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<your SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<formal/default notebook name or id>
SIYUAN_CODEX_NOTEBOOK=CodeX
SIYUAN_ALLOW_RAW_API=false
```

Codex users enter these in the Codex MCP configuration UI. Claude Code users
enter them through the plugin's `userConfig` prompt. Do not commit `.env` or
real tokens.

## Developer Command Mode

For source development, point Codex or Claude Code at the local checkout:

```toml
[mcp_servers.siyuan]
command = "/bin/bash"
args = ["/Users/<you>/projects/siyuan-mcp/scripts/run_siyuan_mcp_uv.sh"]
```

## Verify

```bash
uv run python scripts/smoke_test_mcp.py --config-command --expect-tool siyuan_ping
```

Expected: the server lists `siyuan_*` tools.
