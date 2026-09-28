# SiYuan MCP

General-purpose SiYuan MCP server. This repository exposes low-level SiYuan
tools only: notebooks, documents, blocks, search, attributes, native
database/AttributeView operations, and KMind helpers.

It does not import PDFs, call Zotero, or encode a project-specific note
workflow. Higher-level clients decide where notes should live and how they
should be structured.

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

KMind asset writes and backup-index updates coordinate across cooperating MCP
processes with file locks and atomic replacement. The final asset hash check
runs after the temporary replacement has been written and synced. SiYuan's own
UI does not take these locks; an edit between that final check and replacement
can still race. Re-read the KMind file after a conflict or external edit.

Required local values:

```text
SIYUAN_BASE_URL=http://127.0.0.1:6806
SIYUAN_TOKEN=<your SiYuan API token>
SIYUAN_DEFAULT_NOTEBOOK=<default notebook name or id>
SIYUAN_ALLOW_RAW_API=false
```

For KMind tools on a local SiYuan 3.8.5 instance, also set
`SIYUAN_DATA_DIR` to the absolute `data` directory of that same workspace,
for example `C:/Users/<you>/SiYuan/data`. Recent kernels redact filesystem
paths in `getConf`; KMind cannot discover the directory from that response.
This optional setting is only for KMind's local files, not ordinary API tools.
The Claude plugin prompts for this value as `siyuan_data_dir`; the Codex plugin
shell declares `SIYUAN_DATA_DIR` for local environment injection.
Do not point it at a different workspace or use it with a remote kernel.

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

For the complete offline suite (including KMind plain functions and MCP tool
registration), run `uv sync --locked`, `uv run --no-sync python tests/run_all.py`,
then `uv run --no-sync python scripts/smoke_test_mcp.py --expect-tool siyuan_ping`.
The smoke command without `--ping` does not contact a live kernel.

## Source layout

- `attributeview.py`, `attributeview_rows.py`, `attributeview_views.py`: database
  schema, row/cell and view tools, respectively. `attributeview_values.py` holds
  pure schema/value transformations; `attributeview_api.py` holds shared kernel
  calls and the table-view transaction builder.
- `kmind.py`: SiYuan asset resolution and MCP tools. `kmind_tree.py` contains
  tree/style/outline/diff operations; `kmind_backups.py` owns retention and
  restoration; `kmind_storage.py` owns serialization, locks and atomic writes.
- `server.py`: STDIO entry point, runtime resource, raw API gate, and explicit
  registration of tool groups. `notebooks.py`, `documents.py`, `blocks.py`, and
  `search.py` own the basic notebook/document/block/query tools.
- `core.py`: shared SiYuan transport/configuration and common response helpers;
  `links.py` supplies link helpers.

The external MCP tool contracts are independent of these internal Python module
paths. Run the complete suite when moving an operation between modules.

Tests follow the same domains: `test_attributeview_{schema,rows,views}.py` and
`test_kmind_{resolution,tree,storage,backups}.py`. Run `python tests/run_all.py`
to include both unittest cases and plain test functions; each domain test file
can also be run directly. `test_basic_tools.py` checks MCP dispatch and document
workflows with the SiYuan transport stubbed.

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
