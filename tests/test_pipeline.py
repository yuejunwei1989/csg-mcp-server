"""全链路测试：mock 数据 -> 索引建库 -> 图库查询 -> MCP 工具函数。

运行: python3 tests/test_pipeline.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_data  # noqa: E402
from csg.cli import cmd_index  # noqa: E402
from csg.graphdb import GraphDB  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    assert cond, f"FAIL {name}: {detail}"
    PASS += 1
    print(f"  ok  {name}")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="csg_test_"))
    mock_dir = tmp / "mock"
    mock_data.generate(str(mock_dir))
    db_path = tmp / "graph.db"

    # 1. 索引（含 AST 导出）
    ns = type("NS", (), {})()
    ns.idir = None
    ns.db = str(db_path)
    ns.coverity_home = None
    ns.mock = str(mock_dir)
    ns.ast_regex = "^parse_packet$"
    ns.ast_limit = 10
    cmd_index(ns)

    db = GraphDB(str(db_path))

    # 2. TU
    tus = db.list_tus()
    check("list_tus 数量", len(tus) == 4, str(len(tus)))
    check("TU 编译器为 GHS", all("Green Hills" in t["compiler"] for t in tus))
    packet_tu = next(t for t in tus if "packet.c" in t["primary_file"])
    check("TU 编译参数完整", "-DUSE_CRC32" in packet_tu["args"])

    # 3. 调用关系
    check("who_calls(parse_packet) 含 telemetry_main_task",
          "telemetry_main_task" in db.what_calls("parse_packet"))
    check("what_calls(parse_packet) 含 decode_header",
          "decode_header" in db.called_by("parse_packet"))

    # 4. 影响面：改 crc32_table_lookup 波及 5 个函数
    br = db.blast_radius("crc32_table_lookup")
    expected = {"crc32_verify", "crc32_append", "parse_packet", "encode_packet", "telemetry_main_task"}
    got = set().union(*br["by_depth"].values())
    check("blast_radius 影响面", got == expected, f"got={got}")
    check("blast_radius 深度分层", set(br["by_depth"][1]) == {"crc32_verify", "crc32_append"}
          and set(br["by_depth"][2]) == {"parse_packet", "encode_packet"})

    # 5. 调用路径
    path = db.call_path("telemetry_main_task", "crc32_table_lookup")
    valid = {("telemetry_main_task", "parse_packet", "crc32_verify", "crc32_table_lookup"),
             ("telemetry_main_task", "encode_packet", "crc32_append", "crc32_table_lookup")}
    check("call_path 最短链", path and len(path) == 4 and tuple(path) in valid, str(path))
    check("call_path 无路返回 None", db.call_path("uart_write", "parse_packet") is None)

    # 6. 缺陷
    issues = db.file_issues("packet.c")
    check("file_issues 数量", len(issues) == 2, str(len(issues)))
    first = {i["cid"]: i for i in issues}[1001]
    check("缺陷 CID 1001 NULL_RETURNS", first["checker"] == "NULL_RETURNS" and "NULL" in first["message"])

    # 7. AST
    ast = db.get_ast("parse_packet")
    check("get_ast", ast and ast["name"] == "parse_packet")

    # 8. 搜索
    hits = db.search_entities("crc32*")
    check("search_entities FTS", {h["name"] for h in hits} == {"crc32_verify", "crc32_table_lookup", "crc32_append"}, str(hits))

    # 9. MCP server 工具函数可加载且读同一 db
    os.environ["CSG_DB"] = str(db_path)
    import csg.mcp_server as srv
    tools = [t for t in dir(srv) if not t.startswith("_") and callable(getattr(srv, t))
             and t in {"list_tus", "who_calls", "what_calls", "blast_radius", "call_path",
                       "file_issues", "get_ast", "status", "list_entities", "search_entities",
                       "get_definition"}]
    check("MCP 工具集完整(11个)", len(tools) == 11, str(tools))
    st = json.loads(srv.status())
    check("status 读到索引", st["entities"] == 13 and st["call_edges"] == 11, str(st))

    print(f"\n全部通过: {PASS} 项检查")


if __name__ == "__main__":
    main()
