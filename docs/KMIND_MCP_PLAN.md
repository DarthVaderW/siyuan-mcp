# KMind MCP Notes

This document records the generic KMind tool contract for `siyuan-mcp`.

## Purpose

KMind data is stored by SiYuan as a `.kmind` JSON asset referenced from a
SiYuan document property. The MCP tools provide low-level, safe operations over
that asset:

```text
find/read/export/search
add a node
style a node
validate
diff against a reference
list backups
restore from an explicit backup
```

The MCP does not decide how a caller should classify, organize, or interpret the
mind-map content. Callers provide the target document and the operation.

## Safety Rules

- Read-only tools never write and never create backups.
- `dry_run=true` writes nothing and creates no backup.
- Real writes use optimistic locking through `expected_sha256` when provided.
- Real writes create a backup before modifying the `.kmind` asset.
- Restore defaults to `dry_run=true` and requires an explicit backup identity:
  `backup_path` or `sha256_before`.
- Restore refuses backups recorded for another document.
- Backup paths are constrained to the configured backup directory.

## Backup Storage

New backups are written under:

```text
<SiYuan data dir>/storage/siyuan-mcp-kmind-backups/
```

The backup index is:

```text
backup_index.json
```

For compatibility, tools may read older backups from:

```text
the legacy backup directory configured in code
```

The legacy directory is read-only compatibility storage. New writes must use the
`siyuan-mcp-kmind-backups` directory.

## Deferred Work

Do not add move, delete, import, bulk edit, or broad update tools casually. Any
new write operation must keep the same dry-run, sha guard, and backup rules.
