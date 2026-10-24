# CSG 工具使用指引（给 AI Agent）

本项目接入了 Coverity-Semantic-Graph MCP（工具前缀 `csg`，11 个只读工具）。
这是编译器级 C/C++ 代码知识图谱：所有调用边、定义、TU信息均来自 Coverity
真实编译捕获（含 GHS/IAR 嵌入式编译器语义），可信度高于 grep。

## 何时使用（替代 grep 的场景）

- "哪些文件真正参与编译？编译参数是什么？" → `list_tus`
- "谁调用了函数 X？" → `who_calls`（不要 grep 函数名，会有同名误报）
- "函数 X 调用了谁？" → `what_calls`
- "改函数 X 会影响哪些函数？" → `blast_radius`
- "从 A 到 B 有调用路径吗？" → `call_path`
- "找某个符号定义" → `get_definition` / `search_entities`
- "这个文件有什么静态缺陷？" → `file_issues`
- "这个函数的完整结构（参数/语句）" → `get_ast`

## 何时仍用其他手段

- 读注释、字符串、非符号文本 → grep
- CSG 返回空结果时（可能是索引未覆盖），再回退 grep 并在回答中注明

## 示例问题

- `who_calls` + `blast_radius` 组合回答改动风险评估
- `list_tus` + `file_issues` 组合回答某模块编译与质量状况
