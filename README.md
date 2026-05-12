# SiYuan MCP

Pure SiYuan MCP server for the research system. This repository exposes
low-level SiYuan tools only: documents, blocks, search, attributes, and native
database/AttributeView operations.

It does not import PDFs, call Zotero, implement OpenClaw intake, or encode the
paper-system workflow. Those responsibilities live in sibling repositories.

## Configure

For end users, run the local HTTP runtime and configure these values in Codex
MCP settings as request headers. `.env` remains a developer fallback only.

Required headers for Codex UI URL mode:

```text
Authorization: Bearer <SiYuan API token>
X-SiYuan-Base-Url: http://127.0.0.1:6806
X-SiYuan-Default-Notebook: <formal paper notebook name or id>
X-SiYuan-Codex-Notebook: <CodeX/test notebook name or id>
X-SiYuan-Allow-Raw-API: false
```

`X-SiYuan-Token: <SiYuan API token>` can be used instead of the Authorization
header. Do not commit `.env`.

## Codex MCP Config

Developer stdio mode:

```toml
[mcp_servers.siyuan]
command = "/bin/bash"
args = ["/Users/<you>/projects/siyuan-mcp/scripts/run_siyuan_mcp_uv.sh"]
```

Local HTTP runtime mode:

```bash
scripts/run_siyuan_mcp_http.sh
```

Then add this URL in Codex MCP UI:

```text
http://127.0.0.1:6816/mcp
```

Tokens should be entered by the user in Codex MCP settings as headers, not
committed to Git. Developer command-mode installs may still use local
environment variables or an untracked `.env`:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<formal paper notebook name or id>
SIYUAN_CODEX_NOTEBOOK=<CodeX/test notebook name or id>
SIYUAN_ALLOW_RAW_API=false
```

## Verify

```bash
uv run python scripts/smoke_test_mcp.py --config-command --expect-tool siyuan_ping
uv run python tests/smoke_test_http_mcp.py --expect-tool siyuan_ping
```

Expected: the server lists `siyuan_*` tools.
