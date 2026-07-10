# SiYuan MCP

General-purpose SiYuan MCP server. This repository exposes low-level SiYuan
tools only: notebooks, documents, blocks, search, attributes, native
database/AttributeView operations, and KMind helpers.

It does not import PDFs, call Zotero, or encode a project-specific note
workflow. Higher-level clients decide where notes should live and how they
should be structured.

See [`docs/TOOLS.md`](docs/TOOLS.md) for the full tool contract: what each
`siyuan_*` tool does.

## Install

This repository ships one stdio MCP server. Codex and Claude Code use the same
server, but the ordinary client setup differs.

Prerequisite:

```bash
uv --version
```

If `uv` is not found, install it first. Official installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Homebrew is also fine on macOS:

```bash
brew install uv
```

After installing, restart Codex or Claude Code so the app can see the updated
PATH.

Codex recommended path: add a custom STDIO MCP server in the Codex MCP Servers
settings.

```text
Name: siyuan
Command: uvx
Args:
  --from
  git+https://github.com/DarthVaderW/siyuan-mcp.git@stable
  siyuan-mcp
```

Claude Code recommended path: use the GUI Personal plugins flow, or the
equivalent CLI plugin commands.

```text
Customize -> Personal plugins -> Add
DarthVaderW/siyuan-mcp
```

## Configure

Required local values:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<your SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<default notebook name or id>
SIYUAN_ALLOW_RAW_API=false
```

Codex users enter these in the custom STDIO MCP configuration. Claude Code users
enter them through the plugin's `userConfig` prompt. For current Claude Code
compatibility, the token is stored with the other plugin options instead of
using Claude's `sensitive` userConfig mode. Do not commit `.env` or real tokens.

Codex plugin manifests are still kept in this repository for packaging,
marketplace testing, and possible future Codex plugin improvements. They are not
the ordinary Codex install path right now because plugin-provided MCP rows are
read-only in Codex and do not expose an editable token/config form.

## Upgrade

Codex users refresh the local `uvx @stable` cache, then fully restart Codex:

```bash
uvx --refresh --from git+https://github.com/DarthVaderW/siyuan-mcp.git@stable \
  python -c 'import importlib.metadata as m; print(m.version("siyuan-mcp"))'
```

Do not use `siyuan-mcp --help` as a refresh check. It starts the stdio MCP
server instead of printing normal CLI help.

Existing threads can usually see refreshed MCP tools after restart. If they do
not, open a new thread.

Claude Code users update the marketplace/plugin, then restart Claude Code:

```bash
claude plugin marketplace update darthvaderw-siyuan-mcp
claude plugin update siyuan-mcp@darthvaderw-siyuan-mcp
```

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

## Troubleshooting

If Claude Code reports that the MCP failed to start, check `uv` before
re-entering tokens:

```bash
command -v uv
uv --version
```

`uv: command not found` means the MCP process never started. Install `uv`,
restart Claude Code, then retry the plugin. A missing `uv` can look like a
token/config problem, but the token is not used until the MCP server actually
starts.

If `uv` works but `siyuan_ping` fails, then check:

```text
SiYuan is running
SIYUAN_BASE_URL is http://127.0.0.1:6806 unless you changed the port
SIYUAN_TOKEN matches the token in SiYuan settings
SIYUAN_DEFAULT_NOTEBOOK exists on this computer
```
