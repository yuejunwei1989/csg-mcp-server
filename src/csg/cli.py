"""csg-index CLI：从 Coverity idir 构建图库；csg-mcp 启动 MCP Server。

用法：
  csg-index --idir <idir路径> --db <输出db> [--ast-regex '^(main|init)$']
      [--coverity-home <路径>] [--mock <mock输出目录>]
  csg-mcp  （读取 CSG_DB 环境变量后以 stdio 传输启动）
"""
from __future__ import annotations

import argparse
import json
import re

from .coverity import CovRunner, parse_entities, parse_issues, parse_tus
from .graphdb import GraphDB


def cmd_index(args: argparse.Namespace) -> None:
    runner = CovRunner.from_env()
    runner.idir = args.idir or runner.idir
    if args.mock:
        runner.mock_dir = args.mock
    if args.coverity_home:
        runner.coverity_home = args.coverity_home

    mode = "mock" if runner.is_mock else "real"
    print(f"[csg-index] 模式: {mode}, idir: {runner.idir}")

    if runner.is_mock:
        tus = parse_tus(runner.run(["cov-manage-emit", "list", "--json-output"]))
        entities = parse_entities(
            runner.run(["cov-manage-emit", "find", ".*", "--print-callees", "--json-output"])
        )
    else:
        # 真实模式：cov-manage-emit 原生为文本输出（已实测校准）
        from .coverity import parse_tus_text, parse_entities_text
        tus = parse_tus_text(runner.run(["cov-manage-emit", "list"]))
        entities = parse_entities_text(
            runner.run(["cov-manage-emit", "find", ".*", "--print-callees"])
        )
    print(f"[csg-index] TU: {len(tus)}")
    print(f"[csg-index] 实体: {len(entities)}, 调用边: {sum(len(e.callees) for e in entities)}")

    issues = []
    try:
        issues = parse_issues(runner.run(["cov-format-errors", "--json-output-v10"]))
        print(f"[csg-index] 缺陷: {len(issues)}")
    except (FileNotFoundError, RuntimeError) as exc:
        # Coverity Scan 精简工具链无 cov-format-errors（分析在云端），缺陷可用性降级
        print(f"[csg-index] 缺陷: 跳过（{exc}）")

    db = GraphDB(args.db)
    stats = db.build(tus, entities, issues)
    print(f"[csg-index] 图库已写入 {args.db}: {stats}")

    # 按需导出函数 AST
    if args.ast_regex:
        pat = re.compile(args.ast_regex)
        fns = {e.name for e in entities if e.kind == "function" and pat.match(e.name)}
        for fn in sorted(fns)[: args.ast_limit]:
            try:
                ast = json.loads(
                    runner.run(["cov-manage-emit", "find", fn, "--print-codexm"])
                )
                db.store_ast(fn, ast)
                print(f"[csg-index] AST: {fn}")
            except Exception as exc:  # noqa: BLE001 - 单函数失败不阻断
                print(f"[csg-index] AST 跳过 {fn}: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="csg-index")
    ap.add_argument("--idir", help="Coverity 中间目录（或 CSG_IDIR 环境变量）")
    ap.add_argument("--db", required=True, help="输出 SQLite 图库路径")
    ap.add_argument("--coverity-home", help="Coverity 安装目录（或 COVERITY_HOME）")
    ap.add_argument("--mock", help="模拟输出目录（开发/测试用）")
    ap.add_argument("--ast-regex", default=None, help="仅导出名称匹配的函数 AST")
    ap.add_argument("--ast-limit", type=int, default=50)
    args = ap.parse_args()
    cmd_index(args)


if __name__ == "__main__":
    main()
