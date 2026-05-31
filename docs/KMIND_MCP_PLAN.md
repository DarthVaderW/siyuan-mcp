# KMind MCP Tool Family Plan

This document is a handoff plan for adding KMind support to `siyuan-mcp`.
It is intentionally written as an implementation brief that can be pasted into
Claude Code or Codex.

## Current Codebase

Primary repository:

```text
/Users/wanghaotian/projects/siyuan-mcp
GitHub: https://github.com/DarthVaderW/siyuan-mcp
Purpose: pure SiYuan MCP server
Main file: siyuan_research_mcp/server.py
Docs: docs/
Tests: scripts/smoke_test_mcp.py, tests/
```

Development umbrella repository:

```text
/Users/wanghaotian/projects/research-codex-dev
Purpose: developer-only submodule workspace and compatibility test runner
SiYuan submodule: components/siyuan-mcp
Test runner: scripts/test_all.py
```

Current installed/user-facing MCP route:

```text
Codex GUI custom MCP:
  command: uvx
  args: --from git+https://github.com/DarthVaderW/siyuan-mcp.git@stable siyuan-mcp

Claude Code can use the same stdio MCP command or the Claude plugin wrapper.
Tokens stay in the user's local client config, not Git.
```

Current KMind test document created in SiYuan:

```text
Notebook: CodeX
Doc title: 论文梳理-KMind-Codex测试
Doc ID: 20260531211716-4vgxlex
Doc file: /Users/wanghaotian/SiYuan/data/20260222005018-okt4cvb/20260531211716-4vgxlex.sy
KMind asset: /Users/wanghaotian/SiYuan/data/assets/kmind-doctree-doc-20260531211716-4vgxlex.kmind
```

Original real KMind document, do not edit during tests unless explicitly asked:

```text
Notebook path: /日常/个人/论文梳理
Doc ID: 20260414185947-85w74xn
KMind asset: /Users/wanghaotian/SiYuan/data/assets/kmind-doctree-doc-20260414185947-85w74xn.kmind
```

## Why KMind Belongs In SiYuan MCP

KMind data is not an independent service. In this SiYuan setup, a KMind page is:

```text
SiYuan .sy document
  -> document properties
  -> custom-data-assets-kmind-doctree-doc
  -> data/assets/*.kmind JSON file
```

So KMind tools should live inside `siyuan-mcp` as a dedicated tool family:

```text
siyuan_kmind_*
```

Do not create a separate `kmind-mcp` unless KMind becomes an independent app
outside SiYuan. The tools need SiYuan notebook resolution, document path lookup,
asset path lookup, and safe file writes under the SiYuan workspace.

## Scope

The first version should support reading, exporting, adding, styling, and safe
backups for KMind files. It should not try to implement every KMind UI feature.

Important rule:

```text
MCP = low-level safe operations on KMind JSON.
Skills = research workflow decisions, such as how to classify papers.
```

For example, `siyuan_kmind_add_node` belongs in MCP. A workflow like "add these
papers under sim2real / black-box / residual policy" belongs in the research
paper skill and calls the MCP tools.

## KMind JSON Facts Observed

The `.kmind` file is plain JSON. The current structure includes:

```text
layout
root
  data
    text
    uid
    richText
    expand
    style fields
  children
theme
view
config
localConfig
```

Node text is HTML-like rich text, usually:

```html
<p>Node title</p>
```

Important style fields:

```text
fillColor       node fill color
color           node text color
borderColor     node border color
borderWidth     node border width
borderRadius    node corner radius
fontSize        node font size
fontWeight      node font weight
shape           node shape
paddingX        node horizontal padding
paddingY        node vertical padding
lineColor       connector/branch line color
lineWidth       connector/branch line width
outerFrame      group frame metadata
```

Keep node style and line style separate. Changing `lineColor` changes the branch
line connected to the node, which can visually affect the surrounding map.
Default styling tools must not modify `lineColor`.

## Proposed Tools: Phase 1

Implement these first because they are useful and low risk.

### `siyuan_kmind_find`

Find a KMind document by SiYuan notebook/path or document ID.

Inputs:

```text
path: string | null
notebook: string | null
doc_id: string | null
```

Output:

```json
{
  "docId": "...",
  "docPath": "/...",
  "notebook": "...",
  "title": "...",
  "assetRelPath": "assets/kmind-doctree-doc-....kmind",
  "assetAbsPath": "/Users/.../SiYuan/data/assets/....kmind",
  "sha256": "...",
  "sizeBytes": 23226
}
```

Resolution strategy:

1. If `doc_id` is provided, find the `.sy` document in the SiYuan data folder.
2. If `path` is provided, resolve notebook and document path.
3. Read the document properties.
4. Locate `custom-data-assets-kmind-doctree-doc`.
5. Return asset metadata.

### `siyuan_kmind_read`

Read and summarize a KMind file.

Inputs:

```text
path/notebook/doc_id
max_depth: int = 3
include_styles: bool = false
```

Output:

```json
{
  "docId": "...",
  "title": "...",
  "sha256": "...",
  "root": {"uid": "...", "text": "研究现状"},
  "nodeCount": 89,
  "outline": [...]
}
```

### `siyuan_kmind_export_outline`

Export a KMind file as Markdown outline.

Inputs:

```text
path/notebook/doc_id
max_depth: int | null
```

Output:

```json
{
  "markdown": "- 研究现状\n  - 重定向\n..."
}
```

### `siyuan_kmind_search_nodes`

Search nodes by text.

Inputs:

```text
path/notebook/doc_id
query: string
case_sensitive: bool = false
```

Output should include node UID and full path from root:

```json
{
  "matches": [
    {
      "uid": "kmind-node-...",
      "text": "sim2real-物理参数辨识",
      "path": ["研究现状", "sim2real-物理参数辨识"]
    }
  ]
}
```

### `siyuan_kmind_add_node`

Add a child node under a parent node.

Inputs:

```text
path/notebook/doc_id
parent_uid: string | null
parent_text: string | null
text: string
children: list[string] = []
node_style: dict | null
dry_run: bool = false
expected_sha256: string | null
backup: bool = true
```

Rules:

1. `parent_uid` is preferred.
2. `parent_text` is allowed only if it matches exactly one node.
3. If no parent is provided, add under root.
4. Use `<p>...</p>` rich text.
5. Generate a KMind-style UID.
6. If `dry_run=true`, return planned diff only. Do not write and do not backup.

### `siyuan_kmind_style_node`

Style one node without touching branch lines by default.

Inputs:

```text
path/notebook/doc_id
node_uid: string | null
node_text: string | null
node_style: dict
line_style: dict | null = null
dry_run: bool = false
expected_sha256: string | null
backup: bool = true
```

Default safe node style fields:

```text
fillColor
color
borderColor
borderWidth
borderRadius
fontSize
fontWeight
shape
paddingX
paddingY
```

Do not modify `lineColor` unless `line_style` is explicitly provided.

## Proposed Tools: Phase 2

Add these after Phase 1 is stable.

```text
siyuan_kmind_update_node
siyuan_kmind_move_node
siyuan_kmind_delete_node
siyuan_kmind_bulk_edit
siyuan_kmind_import_outline
siyuan_kmind_list_backups
siyuan_kmind_restore_backup
```

High-risk tools should default to `dry_run=true`:

```text
move_node
delete_node
bulk_edit
import_outline
restore_backup
```

## Backup Policy

Backups are only for KMind write operations. They must not apply to normal
SiYuan documents, blocks, Zotero items, or non-KMind MCP tools.

Tools that must create a backup when they actually write:

```text
siyuan_kmind_add_node
siyuan_kmind_update_node
siyuan_kmind_move_node
siyuan_kmind_delete_node
siyuan_kmind_style_node
siyuan_kmind_bulk_edit
siyuan_kmind_import_outline
siyuan_kmind_restore_backup
```

Tools that must not create backups:

```text
siyuan_kmind_find
siyuan_kmind_read
siyuan_kmind_search_nodes
siyuan_kmind_export_outline
siyuan_kmind_validate
any tool call with dry_run=true
```

Backup location:

```text
SiYuan/data/storage/codex-kmind-backups/
```

Do not store KMind backups under `assets/`, because that would pollute the
attachment area. Do not commit backups to Git.

Backup file naming:

```text
YYYYMMDD-HHMMSS__<doc_id>__before-<operation>.kmind
```

Example:

```text
20260531-212500__20260414185947-85w74xn__before-add-node.kmind
```

Maintain an index file:

```text
SiYuan/data/storage/codex-kmind-backups/backup_index.json
```

Index entry:

```json
{
  "source": "assets/kmind-doctree-doc-20260414185947-85w74xn.kmind",
  "docId": "20260414185947-85w74xn",
  "createdAt": "2026-05-31T21:25:00+08:00",
  "operation": "add_node",
  "sha256Before": "...",
  "sizeBytes": 23226,
  "backupPath": "20260531-212500__20260414185947-85w74xn__before-add-node.kmind"
}
```

Retention policy:

```text
Per KMind document: keep at most 20 backups.
Age limit: delete backups older than 30 days.
Total backup directory: keep under 100 MB.
```

When limits are exceeded, delete oldest backups first and update
`backup_index.json`.

Why this is safe:

```text
Only the changed .kmind file is backed up.
Read-only operations never backup.
Dry runs never backup.
Backups are capped by count, age, and total size.
Most .kmind files are small JSON files, typically KB to low MB.
```

## Concurrency Safety

Before a write, the tool should:

1. Read current `.kmind`.
2. Compute `sha256`.
3. If `expected_sha256` is provided and does not match, refuse to write.
4. Create a backup if this is a real write.
5. Apply edit in memory.
6. Validate JSON.
7. Write back.
8. Re-read and return new `sha256`.

This prevents Codex or Claude Code from overwriting manual edits made in the
KMind UI after the file was read.

## Implementation Notes

Add helpers in `siyuan_research_mcp/server.py` or split into a new module if the
file becomes too large:

```text
siyuan_research_mcp/kmind.py
```

Recommended helper functions:

```text
find_siyuan_data_dir()
resolve_kmind_doc(...)
load_kmind(...)
save_kmind(...)
backup_kmind(...)
cleanup_kmind_backups(...)
walk_kmind_nodes(...)
strip_kmind_html(...)
kmind_html_text(...)
generate_kmind_uid()
apply_node_style(...)
```

Prefer a separate module if adding more than a few hundred lines. Keep MCP tool
functions thin and put logic in helpers that can be unit-tested directly.

UID format should be compatible with existing KMind nodes:

```text
kmind-node-YYYYMMDDHHMMSSmmm-xxxxxxxx
```

Use ASCII code for implementation, but allow Chinese text in JSON content.

## Tests

Use the CodeX test KMind document first:

```text
Doc ID: 20260531211716-4vgxlex
Asset: /Users/wanghaotian/SiYuan/data/assets/kmind-doctree-doc-20260531211716-4vgxlex.kmind
```

Do not test writes against:

```text
/日常/个人/论文梳理
```

until the tools have passed dry-run and backup tests.

Recommended tests:

```text
1. read test:
   siyuan_kmind_read doc_id=20260531211716-4vgxlex

2. search test:
   siyuan_kmind_search_nodes query="Codex 自动修改示例"

3. export test:
   siyuan_kmind_export_outline max_depth=3

4. dry-run add:
   siyuan_kmind_add_node parent_text="Codex 自动修改示例" text="dry-run 节点" dry_run=true
   Assert no file change and no backup.

5. real add:
   same command with dry_run=false.
   Assert backup created, node added, JSON valid.

6. style test:
   style node fillColor/color only.
   Assert lineColor unchanged unless line_style is explicitly provided.

7. sha conflict test:
   call write with wrong expected_sha256.
   Assert write refused and no backup created.

8. retention test:
   create fake backup entries and assert cleanup keeps under configured limits.
```

Existing MCP smoke test should still pass:

```bash
uv run python scripts/smoke_test_mcp.py --config-command --expect-tool siyuan_ping
```

After adding KMind tools, add at least one smoke assertion for:

```text
siyuan_kmind_read
```

## User Experience Target

The intended natural-language workflows are:

```text
读取 /日常/个人/论文梳理，导出前三层大纲。
```

```text
把这 8 篇论文加到 /日常/个人/论文梳理 的 sim2real 分支下，先 dry-run 给我看。
```

```text
把 “Codex 自动修改示例” 改成蓝底白字，但不要改变枝干颜色。
```

```text
列出这个导图最近 10 个 KMind 备份。
```

```text
恢复到上一个备份。恢复前先备份当前版本。
```

## Non-Goals

Do not implement these in the first version:

```text
Full KMind renderer
Image export
Layout engine
Arbitrary visual coordinate editing
Cross-device sync conflict resolver
Full paper ingestion workflow
```

Paper-specific logic belongs in the research paper skill. The MCP should only
provide safe KMind primitives.

