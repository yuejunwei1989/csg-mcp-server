"""Coverity-Semantic-Graph MCP Server（8 个只读查询工具）。"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .graphdb import GraphDB

mcp = FastMCP(
    "coverity-semantic-graph",
    instructions=(
        "编译器级 C/C++ 代码知识图谱（数据源自 Coverity 真实编译捕获）。"
        "查询调用关系/定义/缺陷时优先使用本组工具，替代 grep。"
        "所有调用边均经过编译器验证，含嵌入式编译器(GHS/IAR等)扩展语义。"
    ),
)

_db: GraphDB | None = None


def get_db() -> GraphDB:
    global _db
    if _db is None:
        path = os.environ.get("CSG_DB")
        if not path:
            raise RuntimeError("未设置 CSG_DB 环境变量（SQLite 图库路径）")
        _db = GraphDB(path)
    return _db


@mcp.tool()
def list_tus() -> str:
    """列出真实参与编译的翻译单元（TU）及其完整编译参数。回答"哪些文件真正被编译了"。"""
    import json
    return json.dumps(get_db().list_tus(), ensure_ascii=False)


@mcp.tool()
def list_entities(file: str) -> str:
    """列出指定源文件中定义的全部实体（函数/变量/类型），按行号排序。"""
    import json
    return json.dumps(get_db().file_entities(file), ensure_ascii=False)


@mcp.tool()
def search_entities(query: str, limit: int = 20) -> str:
    """按名称模糊搜索符号（FTS5 全文检索），如 search_entities('parse_*')。"""
    import json
    return json.dumps(get_db().search_entities(query, limit), ensure_ascii=False)


@mcp.tool()
def get_definition(name: str) -> str:
    """获取符号的定义位置（文件:行号）及实体信息。"""
    import json
    return json.dumps(get_db().get_definition(name), ensure_ascii=False)


@mcp.tool()
def who_calls(fn: str) -> str:
    """查询哪些函数调用了 fn（编译器验证的反向调用边）。"""
    import json
    return json.dumps(get_db().what_calls(fn), ensure_ascii=False)


@mcp.tool()
def what_calls(fn: str) -> str:
    """查询 fn 调用了哪些函数（正向调用边）。"""
    import json
    return json.dumps(get_db().called_by(fn), ensure_ascii=False)


@mcp.tool()
def blast_radius(fn: str, max_depth: int = 5) -> str:
    """影响面分析：fn 变更会传播影响到哪些函数（按传播深度分层）。"""
    import json
    return json.dumps(get_db().blast_radius(fn, max_depth), ensure_ascii=False)


@mcp.tool()
def call_path(a: str, b: str, max_depth: int = 8) -> str:
    """搜索 a 到 b 的最短调用路径。返回调用链数组，无路径返回 null。"""
    import json
    return json.dumps(get_db().call_path(a, b, max_depth), ensure_ascii=False)


@mcp.tool()
def file_issues(file: str) -> str:
    """查询指定文件的 Coverity 静态分析缺陷（CID/checker/严重级/位置/描述）。"""
    import json
    return json.dumps(get_db().file_issues(file), ensure_ascii=False)


@mcp.tool()
def get_ast(fn: str) -> str:
    """获取函数级 AST（CodeXM 模型 JSON）。需要索引阶段已导出该函数 AST。"""
    import json
    ast = get_db().get_ast(fn)
    return json.dumps(ast, ensure_ascii=False) if ast else "null"


@mcp.tool()
def status() -> str:
    """索引状态：TU/实体/调用边/缺陷数量及构建时间。"""
    import json
    return json.dumps(get_db().stats(), ensure_ascii=False)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
