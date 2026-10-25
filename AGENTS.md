# AGENTS.md — CSG-MCP-Server 开发指南

> 本文件面向 AI 编码代理（Claude Code / Codex / OpenCode 等），提供继续开发所需的全部上下文。
> 面向使用者的工具说明见 [README.md](README.md) 与 [CLAUDE.md](CLAUDE.md)。

## 项目是什么

Coverity Semantic Graph (CSG)：基于 Coverity 真实编译捕获的编译器级 C/C++ 代码知识图谱。
解决 tree-sitter 系工具的两大缺陷：①拿不到真实参与编译的文件 ②不理解编译器内置语义（GHS/IAR 等）。

- 仓库职责：**后端**（索引器 + MCP Server + LSP Server）
- 配套插件：https://github.com/yuejunwei1989/csg-vscode-extension
- 项目策划书背景：基于 Coverity 的 MCP 开发项目（v0.1 草案，2026-10）

## 代码地图

```
src/csg/
├── coverity.py     # Coverity CLI 封装 + 输出解析（真实模式/mock 模式双驱动）★格式校准主要改这里
├── graphdb.py      # SQLite 图库：TU/实体/调用边/缺陷 + FTS5 + blast_radius/call_path 算法
├── cli.py          # csg-index 索引构建器入口
├── mcp_server.py   # csg-mcp：FastMCP stdio，11 个只读工具
├── lsp_server.py   # csg-ls：手写 JSON-RPC LSP（零第三方框架），definition/references/hover/callHierarchy/诊断
└── agent_setup.py  # csg-agent-setup：生成 Claude Code/Codex/OpenCode 的 MCP 配置
tests/
├── mock_data.py    # 模拟 Coverity CLI 输出（GHS 编译器遥测固件样例项目）
├── test_pipeline.py # 全链路 15 项检查
└── test_lsp.py     # LSP 12 项检查
```

## 关键设计决策（勿破坏）

1. **查询与索引分离**：MCP/LSP 只查预构建 SQLite，任何查询不起 cov 进程；
2. **CLI 为唯一数据出口**：不解析 idir 内部未公开格式（`--print-callees` 原生是文本，本项目约定适配为 JSON）；
3. **mock/real 双驱动**：`CovRunner` 统一入口，`CSG_COV_MOCK` 环境变量切换；
4. **MCP 全只读**：server 不修改 idir、不触发分析；
5. 调用图数据流：`find '.*' --print-callees` → `parse_entities` → `callees` 表（caller/callee 双索引）。

## 常用命令

```bash
pip install -e .                       # 可编辑安装
python3 tests/test_pipeline.py         # 必须全过（15 项）
python3 tests/test_lsp.py              # 必须全过（12 项）
python3 tests/mock_data.py mock_idir && csg-index --db graph.db --mock mock_idir
# LSP stdio 冒烟：CSG_DB=graph.db csg-ls，发 initialize/tools 请求
```

## 当前状态与待办（2026-10-25）

已完成：MVP 全链路 + Coverity Scan 真实工具链 P0 校准（文本解析器，cJSON 实测，见 docs/验证报告-Coverity-Scan.md）
+ LSP v0.2（补全/大纲/全局符号/签名帮助/声明跳转），35 项测试通过，双仓库已部署。

**下一步（按优先级）：**
1. **P0 编译器模板**：用真实 GHS/IAR 项目调通 `cov-configure` 模板（gcc 模板已于 2026-10-25 用 Coverity Scan 工具链实测通过）
2. **P1 缺陷云端化**：Scan 版缺陷在云端，解析 Scan 网页/回执或接入商业版 REST API
3. **P1 CI 集成（gcc/cJSON 链路已预演通过）**：cov-build 产物自动触发 `csg-index` 增量更新
4. **P1 LSP 增强**：实现 references 的精确行号（当前指到调用者函数定义行）、workspace symbol 查询
5. **P2 CodeXM 检查器**：提取数据流语义补充为图库额外边
6. **P2 发布**：PyPI 包 / Open VSX

## 环境约束备忘

- 开发沙箱：api.github.com 可达，github.com:443 被阻断（git push 不可用，用 Contents API）
- mcp 包需固定 `mcp>=1,<2`（2.x 改名 MCPServer，FastMCP 移除）
- Coverity 许可与 GHS/IAR 编译器在用户环境，沙箱中只能用 mock 模式
