# Client Install Notes

This repository is a pure SiYuan MCP. It exposes low-level SiYuan document,
block, search, attribute, and AttributeView/database tools.

This component page keeps the current client-specific setup self-contained for
public users.

## Prerequisite

Make sure `uv` and `uvx` are available to desktop apps:

```bash
uv --version
uvx --version
```

If either command is missing, install `uv` and then restart Codex or Claude
Code:

```bash
brew install uv
```

or:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Codex

Use a custom STDIO MCP entry in Codex.

```text
Name: siyuan
Command: uvx
Args:
  --from
  git+https://github.com/DarthVaderW/siyuan-mcp.git@stable
  siyuan-mcp
```

Configure these values in the same MCP entry:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<your SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<default notebook name or id>
SIYUAN_ALLOW_RAW_API=false
```

Do not use Codex plugin install as the ordinary path for this MCP right now.
Codex plugin-provided MCP rows are read-only and do not currently expose an
editable token/config form. The Codex plugin shell remains in the repository for
packaging, marketplace testing, and possible future Codex plugin improvements.

To upgrade after `stable` moves:

```bash
uvx --refresh --from git+https://github.com/DarthVaderW/siyuan-mcp.git@stable siyuan-mcp --help >/dev/null
```

Then fully restart Codex. Existing threads can see refreshed MCP tools after
restart; if they do not, open a new thread.

## Claude Code

Use the GUI Personal plugins path when available:

```text
Customize -> Personal plugins -> Add
DarthVaderW/siyuan-mcp
```

CLI install is also valid:

```bash
claude plugin marketplace add DarthVaderW/siyuan-mcp
claude plugin install siyuan-mcp@darthvaderw-siyuan-mcp
```

Claude Code prompts for the same local values through `userConfig`. For current
Claude Code compatibility, the token is stored with the other plugin options
instead of using Claude's `sensitive` userConfig mode. This is local to the
user's machine, but it is not keychain-backed.

To upgrade:

```bash
claude plugin marketplace update darthvaderw-siyuan-mcp
claude plugin update siyuan-mcp@darthvaderw-siyuan-mcp
```

Restart Claude Code after updating.

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

The smoke test verifies MCP tool discovery. `siyuan_ping` requires SiYuan
running locally and a valid token.

## Claude Code Startup Failure

If Claude Code suggests the token or `userConfig` may be wrong, first verify
that `uv` exists:

```bash
command -v uv
uv --version
```

When `uv` is missing, Claude Code cannot start the MCP server at all. Install
`uv`, restart Claude Code, and retry before changing the SiYuan token.
