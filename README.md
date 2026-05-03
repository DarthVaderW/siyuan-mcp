# SiYuan MCP

Pure SiYuan MCP server for the research system. This repository exposes
low-level SiYuan tools only: documents, blocks, search, attributes, and native
database/AttributeView operations.

It does not import PDFs, call Zotero, implement OpenClaw intake, or encode the
paper-system workflow. Those responsibilities live in sibling repositories.

## Configure

Create a local `.env` from `.env.example`:

```bash
cp .env.example .env
```

Required:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<formal paper notebook name or id>
SIYUAN_CODEX_NOTEBOOK=<CodeX/test notebook name or id>
SIYUAN_ALLOW_RAW_API=false
```

Do not commit `.env`.

## Codex MCP Config

```toml
[mcp_servers.siyuan]
command = "/bin/bash"
args = ["/Users/<you>/projects/siyuan-mcp/scripts/run_siyuan_mcp_uv.sh"]
```

Codex config should contain command/args only. Keep tokens in `.env`.

## Verify

```bash
uv run python scripts/smoke_test_mcp.py --config-command --expect-tool siyuan_ping
```

Expected: the server lists `siyuan_*` tools.
