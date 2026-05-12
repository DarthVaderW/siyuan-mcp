# Codex Install

This repository is a pure SiYuan MCP. It exposes low-level SiYuan document,
block, search, attribute, and AttributeView/database tools.

## Simple URL Mode

Run the local HTTP runtime:

```bash
scripts/run_siyuan_mcp_http.sh
```

Then open Codex Settings -> MCP and add a URL MCP:

```text
URL: http://127.0.0.1:6816/mcp
```

Add headers in Codex UI:

```text
Authorization: Bearer <your SiYuan API token>
X-SiYuan-Base-Url: http://127.0.0.1:6806
X-SiYuan-Default-Notebook: <formal notebook name or id>
X-SiYuan-Codex-Notebook: <CodeX/test notebook name or id>
X-SiYuan-Allow-Raw-API: false
```

You can use `X-SiYuan-Token: <your token>` instead of the Authorization header
if that is easier in your Codex UI.

## Developer Command Mode

For development, Codex can start the MCP with a local command:

```toml
[mcp_servers.siyuan]
command = "/bin/bash"
args = ["/Users/<you>/projects/siyuan-mcp/scripts/run_siyuan_mcp_uv.sh"]
```

In command mode, configure secrets with shell environment variables or an
untracked `.env` in this repository:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<your SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<formal notebook name or id>
SIYUAN_CODEX_NOTEBOOK=<CodeX/test notebook name or id>
SIYUAN_ALLOW_RAW_API=false
```

Do not commit `.env` or real tokens.

## Verify

```bash
uv run python scripts/smoke_test_mcp.py --config-command --expect-tool siyuan_ping
uv run python tests/smoke_test_http_mcp.py --expect-tool siyuan_ping
```

The smoke tests verify MCP tool discovery. `siyuan_ping` requires SiYuan running
locally and a valid token.
