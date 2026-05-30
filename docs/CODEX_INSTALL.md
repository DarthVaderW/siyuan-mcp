# Codex And Claude Code Install

This repository is a pure SiYuan MCP. It exposes low-level SiYuan document,
block, search, attribute, and AttributeView/database tools.

## Codex Plugin Install

Make sure `uvx` is available before installing the plugin:

```bash
uvx --version
```

If it is missing, install `uv` from Astral:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then restart Codex or Claude Code so the updated PATH is picked up.

Install the public marketplace and plugin:

```bash
codex plugin marketplace add DarthVaderW/siyuan-mcp --ref stable \
  --sparse .agents/plugins \
  --sparse plugins/siyuan-mcp
codex plugin add siyuan-mcp@siyuan-mcp
```

Then configure these values in Codex Settings -> MCP:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<your SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<formal/default notebook name or id>
SIYUAN_CODEX_NOTEBOOK=CodeX
SIYUAN_ALLOW_RAW_API=false
```

The plugin starts the stdio MCP with `uvx` from a fixed release tag; no local
HTTP service is required, and normal MCP startup does not auto-refresh from
GitHub.

## Claude Code Plugin Install

Inside Claude Code:

```text
/plugin marketplace add DarthVaderW/siyuan-mcp
/plugin install siyuan-mcp@darthvaderw-siyuan-mcp
```

Claude Code prompts for the same local values through `userConfig`. For current
Claude Code compatibility, the token is stored with the other plugin options
instead of using Claude's `sensitive` userConfig mode. This is local to the
user's machine, but it is not keychain-backed.

## Developer Command Mode

For development, clients can start the MCP with a local command:

```toml
[mcp_servers.siyuan]
command = "/bin/bash"
args = ["/Users/<you>/projects/siyuan-mcp/scripts/run_siyuan_mcp_uv.sh"]
```

Do not commit `.env` or real tokens.

## Verify

```bash
uv run python scripts/smoke_test_mcp.py --config-command --expect-tool siyuan_ping
```

The smoke tests verify MCP tool discovery. `siyuan_ping` requires SiYuan running
locally and a valid token.

## Claude Code Startup Failure

If Claude Code suggests the token or `userConfig` may be wrong, first verify
that `uvx` exists:

```bash
command -v uvx
uvx --version
```

When `uvx` is missing, Claude Code cannot start the MCP server at all. Install
`uv`, restart Claude Code, and retry before changing the SiYuan token.
