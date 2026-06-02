# Tool Contract

这份文档记录当前 SiYuan MCP 暴露给上层调用方的工具语义。原则是：
MCP 提供通用思源能力，上层调用方决定具体业务流程。

## 连接和笔记本

### `siyuan_ping`

检查思源内核、token、版本和笔记本列表。

### `siyuan_list_notebooks`

列出思源笔记本。

### `siyuan_ensure_notebook`

按名称查找笔记本，不存在时可创建。

## 文档创建和定位

### `siyuan_create_doc`

用 Markdown 创建文档。重复调用同一路径时，思源不会覆盖已有文档。

### `siyuan_ensure_doc`

按 human-readable path 查找或创建文档，并可设置 `custom-*` 属性。上层调用方可用它创建有稳定路径和元数据的主键文档。

### `siyuan_get_doc_id_by_path`

把 human-readable path 解析为文档 ID。

### `siyuan_get_doc_paths_by_id`

根据文档 ID 返回 human-readable path 和底层 storage path。

## 内部链接

### `siyuan_make_block_link`

根据块或文档 ID 生成标准 `siyuan://blocks/...` Markdown 链接。调用方传入显示文本，工具负责校验 ID 并转义链接标签。

### `siyuan_make_doc_link`

根据 human-readable path 解析文档 ID，并生成标准文档链接。路径命中多个文档时不会猜测；返回候选链接列表，由调用方或用户选择。

## 文档级操作

这些工具走思源 filetree API，适合操作文档根。不要用 `siyuan_delete_block` 删除文档根，除非你明确想要块级行为。

### `siyuan_remove_doc_by_id`

按文档 ID 删除，随后 flush SQLite transaction，并可验证 SQL 中不再残留文档行。

### `siyuan_remove_doc_by_path`

按 human-readable path 删除。内部会先解析文档 ID，再调用 `siyuan_remove_doc_by_id`。

### `siyuan_rename_doc_by_id`

按文档 ID 重命名。

### `siyuan_rename_doc_by_path`

按 human-readable path 找到文档后重命名。

### `siyuan_move_docs_by_id`

把一组文档 ID 移动到目标父文档 ID 或目标笔记本 ID 下。

### `siyuan_move_doc_by_path`

把单个 human-readable path 文档移动到目标父路径或笔记本根目录。

## 块级操作

### `siyuan_get_block_markdown`

读取块或文档的 Kramdown/Markdown。

### `siyuan_insert_block`

向父块 append 或 prepend Markdown/DOM。

### `siyuan_update_block`

替换块内容。

### `siyuan_delete_block`

删除块。适合段落、列表、标题等块，不推荐用于文档根删除。

## 属性和搜索

### `siyuan_get_block_attrs`

读取块属性。

### `siyuan_set_block_attrs`

设置块属性。机器可读元信息建议使用 `custom-*`：

```json
{
  "custom-type": "project-note",
  "custom-project": "example",
  "custom-status": "active"
}
```

### `siyuan_find_docs_by_attrs`

查找 IAL 中包含指定属性的文档根。适合按 `custom-type`、`custom-project`、`custom-status` 等稳定元数据查找。

### `siyuan_sql_query`

只读 SQL 查询。只允许 `SELECT`、`WITH`、`PRAGMA`。

### `siyuan_search_blocks`

基于 SQL 的简单文本搜索。

## 文档追加

### `siyuan_upsert_doc_section`

确保文档存在，然后追加一个标题段落。适合日志、变更记录、普通文档追加。

## 思源数据库/属性视图

### `siyuan_av_search`

搜索思源数据库/属性视图。

### `siyuan_av_get`

读取属性视图的底层 JSON。适合检查字段 ID、字段类型、视图 ID 和已有行。

### `siyuan_av_render`

渲染思源数据库/属性视图。支持传入 `blockId`，并可用 `createIfNotExist=true` 为一个新的 `NodeAttributeView` 块初始化数据库 JSON。

### `siyuan_av_add_key`

给属性视图增加字段。当前已验证的常用字段类型包括 `text`、`number`、`url`、`select`、`mSelect`、`checkbox`。

默认行为是把新字段追加到当前最后一个字段之后；如果确实要插到最前面，显式传 `previousKeyId=""`。

### `siyuan_av_remove_key`

删除数据库字段。创建新表时可用它移除思源默认生成但不需要的“单选”列。

### `siyuan_av_sort_key`

调整数据库全局字段顺序。通常应把 `block` 类型的“主键”字段放在第一位。

### `siyuan_av_sort_view_key`

调整当前表格视图中的列顺序。通常和 `siyuan_av_sort_key` 配套使用：全局字段顺序和可见视图列顺序都整理成同一个模板。

### `siyuan_av_append_detached_rows`

向属性视图追加非绑定行。行结构使用简单对象：

```json
{
  "primary": "Test Humanoid PPO Locomotion",
  "values": {
    "字段ID": "字段值"
  }
}
```

工具会根据字段类型转换成思源 AV value JSON。

### `siyuan_av_ensure_bound_rows`

确保已有思源文档或块作为数据库主键行存在，然后写入字段。需要保留“文档即主键”结构时应优先使用这个工具。

```json
{
  "avId": "数据库ID",
  "databaseBlockId": "数据库块ID",
  "rows": [
    {
      "blockId": "主键文档ID",
      "values": {
        "字段ID": "字段值"
      }
    }
  ]
}
```

工具会先通过 `getAttributeViewItemIDsByBoundIDs` 检查是否已绑定，缺失时再调用 `addAttributeViewBlocks`，因此重复调用不会重复添加同一个主键文档。

### `siyuan_av_set_cell`

更新一个单元格。适合在已知 `avId`、`keyId`、`itemId` 后修改字段。

### `siyuan_av_batch_set_cells`

批量更新多个单元格。适合一次写入多个字段。

## KMind

KMind 工具操作思源文档关联的 `.kmind` 资产文件。读取工具不写文件；写入工具默认带备份，并支持 `dry_run` 和 `expected_sha256` 做人工确认与并发保护。备份默认写入 `storage/siyuan-mcp-kmind-backups`，历史 `storage/codex-kmind-backups` 只读兼容。

### `siyuan_kmind_find`

通过文档路径或文档 ID 定位 KMind 资产，返回文档、资产路径、大小和 sha256 等元数据。

### `siyuan_kmind_read`

读取 KMind 并返回结构化 outline，可限制深度并选择是否包含样式字段。

### `siyuan_kmind_export_outline`

把 KMind 导出为 Markdown bullet outline。适合人工审阅或把脑图内容转成普通文本。

### `siyuan_kmind_search_nodes`

按节点文本搜索，返回匹配节点的 uid、文本和从根节点到该节点的路径。

### `siyuan_kmind_add_node`

向根节点或指定父节点追加子节点，可同时添加一层子节点。写入前可用 `dry_run=true` 预览；正式写入建议传 `expected_sha256`。

### `siyuan_kmind_style_node`

修改单个节点的安全样式字段。节点内容、移动、删除和批量结构改写不属于这个工具的职责。

### `siyuan_kmind_validate`

校验 KMind JSON 是否存在合法根节点，返回节点数量、sha256 和顶层字段。

### `siyuan_kmind_diff`

把当前 KMind 与指定备份、sha256 或外部 `.kmind` 文件比较。默认选择该文档最新备份；无参考版本时返回明确状态。

### `siyuan_kmind_list_backups`

列出某个 KMind 文档的备份，包含当前备份目录和历史只读备份目录中的记录。

### `siyuan_kmind_restore_backup`

从同一文档的备份恢复 KMind。默认 `dry_run=true`，必须显式指定备份文件名或 sha256；正式恢复会先给当前文件再做一次备份。

## 兜底 API

### `siyuan_call_api`

原始 `/api/...` 兜底工具，默认关闭。只有在 `SIYUAN_ALLOW_RAW_API=true` 时可用。

使用规则：

- 只调用 `/api/...`。
- 复杂写操作先在测试文档验证。
- 用完建议关回 `SIYUAN_ALLOW_RAW_API=false`。
