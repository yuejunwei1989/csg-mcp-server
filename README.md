# Coverity Semantic Graph (CSG) — Server

基于 **Coverity 真实编译捕获**的编译器级 C/C++ 代码知识图谱服务端。
为 AI Agent（MCP 协议）与编辑器（LSP 协议）提供"编译器验证过"的代码语义查询，
解决 tree-sitter 系图谱工具拿不到真实编译文件、不理解编译器内置语义的问题。

配套 VSCode 插件见独立仓库：[csg-vscode-extension](https://github.com/yuejunwei1989/csg-vscode-extension)。

## 架构

```
cov-build/--dir idir（任意编译器，含 GHS/IAR 模板）
   → csg-index：cov-manage-emit / cov-format-errors 出口解析 → SQLite 图库
   → csg-mcp：FastMCP stdio server，11 个只读查询工具（AI Agent 用）
   → csg-ls：  LSP server（编辑器用，复用同一图库）
```

- **查询与索引分离**：MCP/LSP 只查预构建库，不起 cov 进程，毫秒级响应
- **CLI 为唯一数据出口**：不解析 idir 内部未公开格式
- **一次建库、多端消费**：AI Agent 与 VSCode 插件共享同一份编译器级事实

## 安装

```bash
pip install .          # Python ≥ 3.10, mcp>=1,<2
```

安装后得到 4 个命令：`csg-index` / `csg-mcp` / `csg-ls` / `csg-agent-setup`。

## 构建索引

```bash
# 真实模式（需 Coverity 许可）
csg-index --idir /path/to/idir --db ./graph.db \
          --coverity-home /opt/coverity --ast-regex '^(main|parse_packet)$'

# 模拟模式（无 Coverity 环境，开发/测试）
python3 tests/mock_data.py mock_idir
csg-index --db ./graph.db --mock mock_idir
```

## 接入 AI Agent（MCP）

```bash
csg-agent-setup --db ./graph.db --scope user --only claude,codex,opencode
```

- **Claude Code**：写入 `~/.claude.json`（user）或 `.mcp.json`（project）
- **Codex CLI**：写入 `~/.codex/config.toml` 的 `[mcp_servers.csg]`
- **OpenCode**：写入 `~/.config/opencode/opencode.json` 的 `mcp` 段

也可手动配置：

```json
// Claude Code / .mcp.json
{ "mcpServers": { "csg": { "command": "csg-mcp", "env": { "CSG_DB": "/abs/graph.db" } } } }
```

```toml
# Codex CLI / ~/.codex/config.toml
[mcp_servers.csg]
command = "csg-mcp"
[mcp_servers.csg.env]
CSG_DB = "/abs/graph.db"
```

## 接入编辑器（LSP）

```bash
CSG_DB=/abs/graph.db csg-ls   # 任何 LSP 客户端均可接入
```

- **VSCode**：直接使用 [csg-vscode-extension](https://github.com/yuejunwei1989/csg-vscode-extension)（已打包 vsix，设置 `csg.dbPath` 即可）
- **Neovim / 其他编辑器**：将 `csg-ls` 配置为 C/C++ 的 language server

LSP 提供：定义跳转、查找引用、悬停（实体+编译器+缺陷数）、调用层级、Coverity 缺陷诊断。

## MCP 工具（11 个，只读）

| 工具 | 功能 |
|------|------|
| `list_tus()` | 真实参与编译的 TU 及完整编译参数 |
| `list_entities(file)` | 文件内全部实体 |
| `search_entities(query)` | FTS5 符号模糊搜索 |
| `get_definition(name)` | 定义位置 |
| `who_calls(fn)` / `what_calls(fn)` | 编译器验证的调用边（反向/正向） |
| `blast_radius(fn)` | 变更影响面（按传播深度分层） |
| `call_path(a, b)` | 最短调用路径 |
| `file_issues(file)` | Coverity 缺陷（CID/checker/严重级） |
| `get_ast(fn)` | 函数级 AST（CodeXM 模型） |
| `status()` | 索引状态 |

## 测试

```bash
python3 tests/test_pipeline.py   # 15 项检查：mock 数据→索引→建库→查询→MCP
python3 tests/test_lsp.py        # 12 项检查：definition/references/hover/callHierarchy/诊断
```

## 格式校准（接入真实 idir 时必读）

`src/csg/coverity.py` 中的解析层按 Coverity 官方文档输出格式实现：
`tus.json`（`cov-manage-emit list`）、`callees.json`（`find '.*' --print-callees`）、
`issues.json`（`cov-format-errors --json-output-v10`，官方格式）。

`--print-callees` 原生为文本输出，本项目约定适配为 JSON。接入真实环境时：

1. 在真实 idir 上运行 `cov-manage-emit --dir idir find '.*' --print-callees > sample.txt`；
2. 在 `parse_entities` 中新增文本解析分支（或写脚本转成适配 JSON）；
3. 对照 `build-log.txt` 与官方文档校验 `--json-output-v10` schema 差异；
4. CI 中每次 Coverity 升级后重跑 `tests/test_pipeline.py` + 真实抽样比对。

## 已知限制

- `--print-codexm` 为按函数导出，全程序图需基于 callees/definitions 拼装
- 深层语义（数据流路径）建议用 CodeXM 自定义检查器补充为额外节点
- 解析层输出格式依赖 Coverity 版本，升级需回归测试

## 许可

本项目代码随附于仓库，Coverity 本身为商业软件，使用需自备许可。
