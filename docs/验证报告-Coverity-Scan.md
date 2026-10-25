# CSG 工具链验证报告：基于 Coverity Scan 免费工具链的实测

> 版本：v1.0 ｜ 日期：2026-10-25 ｜ 环境：Ubuntu 沙箱 + Coverity Scan 精简工具链
> 对应项目：[csg-mcp-server](https://github.com/yuejunwei1989/csg-mcp-server)

---

## 1. 验证目标

验证 CSG（Coverity Semantic Graph）工具链的核心假设：

1. **可行性**：免费的 Coverity Scan 工具链能否支撑 CSG 的"编译器级知识图谱"路线；
2. **格式校准（P0）**：`cov-manage-emit` 真实输出格式与开发期假设是否一致，解析层是否需要修正；
3. **端到端正确性**：真实 idir → 建库 → 查询（定义/调用边/影响面/调用路径）全链路是否产出编译器级准确结果。

## 2. 验证环境与方法

### 2.1 环境

| 组件 | 版本/来源 |
|------|-----------|
| Coverity Scan 工具链 | `scan.coverity.com/download/cxx/linux64`，token 认证下载，1.28GB |
| 验证项目 | **cJSON v1.7.18**（真实开源 C 库，~90 个公开 API，源码约 3000 行） |
| 编译器 | 系统 gcc（`cov-configure --gcc` 内置模板） |
| 构建捕获 | `bear -- make`（对照组）+ `cov-build --dir idir make`（实验组） |
| 调用图对照 | GNU cflow（`--preprocess="gcc -E <真实编译参数>"`） |

### 2.2 方法：三层递进验证

```
第 1 层  mock 单元验证      → tests/mock_data.py + 27 项测试（格式假设自洽性）
第 2 层  真实项目模拟验证   → tests/cov_sim.py（bear+cflow 生成适配格式，验证管线健壮性）
第 3 层  真实 Coverity 验证 → 真实 idir + 文本解析器（本报告核心）
```

### 2.3 关键命令序列

```bash
# 下载工具链（token + 项目名认证）
curl -o cov-tool.tar.gz "https://scan.coverity.com/download/cxx/linux64" \
     --data "token=<TOKEN>&project=yuejunwei1989/csg-mcp-server"

# 真实编译捕获
cov-configure --gcc
cov-build --dir idir make -f Makefile     # → Emitted 4 C/C++ compilation units (100%)

# 导出真实语义数据
cov-manage-emit --dir idir list                        # TU 列表
cov-manage-emit --dir idir find '.*' --print-callees   # 实体 + 调用边

# 建库与查询
csg-index --idir idir --db graph.db --coverity-home /path/to/cov-analysis
```

---

## 3. 发现与结论

### 3.1 发现一：真实输出为文本格式（P0 校准完成）

开发期 mock 假设 `cov-manage-emit` 输出 JSON，**实测为固定缩进的文本格式**：

```
# list
Translation unit:
1 -> /tmp/real_proj/cJSON.c

# find --print-callees
Matching function: cJSON_ParseWithOpts
 declared at:
   /tmp/real_proj/cJSON.c:1088:23-/tmp/real_proj/cJSON.c:1088:41
 defined in TU 1 with row 69
Calls:
 Call to: cJSON_ParseWithLengthOpts
   declared at:
     /tmp/real_proj/cJSON.c:1104:23-...
```

**处置**：实现 `parse_tus_text` / `parse_entities_text` 文本解析器，`csg-index` 按模式自动分流（mock→JSON 适配格式，real→原生文本）。实测解析后建库成功。

### 3.2 发现二：Coverity Scan 为精简工具链

下载包只含 **capture 侧命令**（`cov-build`/`cov-configure`/`cov-manage-emit`/`cov-emit*`），**不含** `cov-analyze`/`cov-format-errors`（分析在 Scan 云端执行，缺陷需上传后在网页查看）。

**处置**：
- `csg-index` 对 `cov-format-errors` 缺失做容错降级（跳过缺陷、不阻断建图）；
- 缺陷查询（`file_issues`）在 Scan 模式下不可用，属已知限制；商业版环境不受影响；
- 可选后续：解析 Scan 网页/上传包回执获取云端缺陷（P2）。

### 3.3 发现三：编译器级语义的价值得到量化印证

三个数据源在**同一项目**上的抽取能力对比：

| 数据源 | 实体数 | 调用边数 | 缺陷说明 |
|--------|--------|---------|----------|
| cflow 默认预处理器 | ~48 | ~20 | **宏包装函数全部丢失**（cJSON 的 `CJSON_PUBLIC(x)` API 无一识别） |
| cflow + gcc -E 真实宏展开 | 153→201 | 229→288 | 静态函数覆盖完整，但无宏/间接调用边 |
| **Coverity cov-build（编译器级）** | **177（去重）/311（原始）** | **539** | 编译器实际解析的全部符号与调用，含宏展开后的真实边 |

**结论**：仅"让预处理器看懂宏"这一件事，就使函数识别率提升 3~4 倍；编译器级捕获的调用边比最优的外部工具多 92%。这从量化上印证了项目立论——**tree-sitter 系工具（不做预处理）在真实宏密集代码上会漏掉大部分语义**，嵌入式场景（GHS/IAR 的 `__interrupt`、`#pragma location` 等扩展只会更严重）尤甚。

### 3.4 发现四：cflow 的工程教训（已沉淀为 cov_sim.py）

模拟器开发过程中发现 `cflow` 两个坑：①多文件一次调用会提前终止（需逐文件运行合并）；②默认内置预处理器不展开项目宏（需 `--preprocess="gcc -E <真实编译参数>"`）。修复后 cflow 可作为无 Coverity 环境下的**管线回归数据源**（`tests/cov_sim.py`）。

### 3.5 端到端查询正确性（真实 Coverity 数据）

| 查询 | 结果 | 验证点 |
|------|------|--------|
| `get_definition('cJSON_Parse')` | `cJSON.c:1184` | 与源码实际定义行一致 |
| `called_by('cJSON_Parse')` | `cJSON_ParseWithOpts` | 与源码调用关系一致 |
| `who_calls('parse_value')` | `cJSON_ParseWithLengthOpts`、`parse_array`、`parse_object` | 跨函数多调用者完整 |
| `blast_radius('cJSON_New_Item')` | 3 层传播，52 个函数（17/25/10） | 影响面分层合理 |
| `list_tus` | 4 TU：cJSON.c×2、cJSON_Utils.c、test.c | 与 cov-build 输出一致 |

---

## 4. 结论与建议

1. **可行性结论：成立**。免费 Coverity Scan 工具链完整支撑 CSG 的 capture→emit→建库→查询链路，核心假设（真实编译文件 + 编译器级语义）全部落地；
2. **P0 格式校准已完成**，解析层已实测校准并推送仓库；剩余 P0 项仅剩 **GHS/IAR 自定义模板**（需商业环境）；
3. **对嵌入式项目的建议**：本验证用 gcc，宏复杂度远低于典型固件代码；GHS/IAR 环境部署时应优先验证 `cov-configure` 对编译器扩展关键字（`__interrupt`/`__no_init` 等）的处理，预期收益比 cJSON 本例更大；
4. **风险提示**：
   - Scan 精简版无本地缺陷导出，缺陷相关 MCP 工具需商业版或云端解析；
   - `cov-manage-emit` 文本格式无官方稳定承诺，Coverity 升级后需用 `tests/calibrate.sh` 重跑回归；
5. **复现方式**：仓库内 `tests/cov_sim.py`（无 Coverity 环境回归）+ `tests/calibrate.sh`（真实环境校准），验证流程全程可重复。

## 附录：验证产物清单

| 产物 | 位置 | 说明 |
|------|------|------|
| 文本解析器 | `src/csg/coverity.py`（`parse_tus_text`/`parse_entities_text`） | 实测格式校准 |
| 模式分流 | `src/csg/cli.py` | mock=JSON 适配 / real=原生文本 |
| 缺陷容错 | `src/csg/cli.py` | Scan 精简链无 cov-format-errors 时降级 |
| cflow 模拟器 | `tests/cov_sim.py` | 真实项目生成适配格式 |
| 校准脚本 | `tests/calibrate.sh` | 真实环境导出标准样本 |
| 回归测试 | 27 项（15+12） | 校准后全过 |
