# 在 Codex 中安装 SiYuan MCP

这个仓库是纯 SiYuan MCP。它是标准 stdio MCP server，可以被支持 MCP 的 Codex 客户端挂载。

## 安装依赖

在项目目录执行：

```bash
python -m pip install -e .
```

## 本机开发版

Windows 示例：

```toml
[mcp_servers.siyuan]
command = "C:\\Users\\Haoti\\Documents\\Codex\\2026-04-28\\mcp-zotero-codex\\scripts\\run_siyuan_mcp_uv.cmd"
args = []
```

Mac 示例：

```toml
[mcp_servers.siyuan]
command = "python"
args = ["/Users/haoti/path/to/siyuan-mcp/siyuan_research_mcp/server.py"]
```

服务会自动读取项目根目录的 `.env`。Codex MCP 配置和可视化配置界面建议只长期保存 `command` 和 `args`，不要保存真实 token。临时测试可以显式传 `env`，但正式多机配置以本机 `.env` 为准。

本机 Windows 的可复制配置也保存在 `docs/CODEX_CONFIG_SNIPPET.toml`。

## Node 备用版

如果临时需要使用 Node 版：

```toml
[mcp_servers.siyuan-node]
command = "node"
args = ["C:\\Users\\Haoti\\Documents\\Codex\\2026-04-28\\mcp-zotero-codex\\src\\server.js"]
```

## 推荐的跨设备方式

1. 把项目上传到私有 GitHub 仓库。
2. 不要上传 `.env`。
3. 每台设备 clone 仓库。
4. 每台设备各自创建自己的 `.env`。
5. Codex 配置指向本机 clone 后的 wrapper 或 `siyuan_research_mcp/server.py`。

## 未来包安装方式

如果后续要做成真正可安装包，可以走两条路线：

- Node/npm：发布到 npm 或用 GitHub repo 安装，然后通过 `npx` 启动。
- Python/uv：改写成 Python 包，然后通过 `uvx` 或 `uv run` 启动。

当前版本先用本地路径最稳，方便快速改工具和调试思源 API。

## 一键安装到 Codex

在普通终端里运行：

```bash
python scripts/install_into_codex.py
```

它会更新：

```text
~/.codex/config.toml
```

并复制仓库里的 skill 到：

```text
~/.codex/skills
```

先预览可以运行：

```bash
python scripts/install_into_codex.py --dry-run
```
