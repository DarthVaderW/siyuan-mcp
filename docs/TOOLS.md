# Tool Contract

这份文档记录当前 SiYuan MCP 暴露给上层 skill 的工具语义。原则是：MCP 提供思源能力，skill 决定业务流程。

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

按 human-readable path 查找或创建文档，并可设置 `custom-*` 属性。上层 skill 应优先使用它创建论文、作者、单位、Codex 方案等主键文档。

### `siyuan_get_doc_id_by_path`

把 human-readable path 解析为文档 ID。

### `siyuan_get_doc_paths_by_id`

根据文档 ID 返回 human-readable path 和底层 storage path。

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
  "custom-type": "paper",
  "custom-zotero-item-key": "ABCD1234",
  "custom-arxiv-id": "2501.00001"
}
```

### `siyuan_find_docs_by_attrs`

查找 IAL 中包含指定属性的文档根。适合按 `custom-type`、`custom-project`、`custom-arxiv-id`、`custom-zotero-item-key` 等稳定元数据查找。DOI 留在 Zotero 元数据中，不作为思源核心检索字段。

### `siyuan_sql_query`

只读 SQL 查询。只允许 `SELECT`、`WITH`、`PRAGMA`。

### `siyuan_search_blocks`

基于 SQL 的简单文本搜索。

## 经验和日志

### `siyuan_upsert_doc_section`

确保文档存在，然后追加一个标题段落。适合日记、Codex 解决方案、阅读日志。

### `siyuan_append_experience_note`

把可复用经验追加到 `CodeX/MCP/经验库` 约定位置。适合记录 Windows、shell、编码、PATH、MCP、思源 API、Zotero 集成等踩坑。

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

调整数据库全局字段顺序。正式论文表应把 `block` 类型的“主键”字段放在第一位。

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

确保已有思源文档或块作为数据库主键行存在，然后写入字段。论文总表、领域表、作者表、单位表应优先使用这个工具，因为它保留“笔记即主键”的结构。

```json
{
  "avId": "数据库ID",
  "databaseBlockId": "数据库块ID",
  "rows": [
    {
      "blockId": "论文笔记文档ID",
      "values": {
        "字段ID": "字段值"
      }
    }
  ]
}
```

工具会先通过 `getAttributeViewItemIDsByBoundIDs` 检查是否已绑定，缺失时再调用 `addAttributeViewBlocks`，因此重复调用不会重复添加同一篇论文。

### `siyuan_av_set_cell`

更新一个单元格。适合在已知 `avId`、`keyId`、`itemId` 后修改字段。

### `siyuan_av_batch_set_cells`

批量更新多个单元格。适合论文元数据同步时一次写入多个字段。

## 兜底 API

### `siyuan_call_api`

原始 `/api/...` 兜底工具，默认关闭。只有在 `SIYUAN_ALLOW_RAW_API=true` 时可用。

使用规则：

- 只调用 `/api/...`。
- 复杂写操作先在测试文档验证。
- 用完建议关回 `SIYUAN_ALLOW_RAW_API=false`。
