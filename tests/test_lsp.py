"""csg-ls 测试：复用 mock 图库，验证 definition/references/hover/callHierarchy/diagnostics。

运行: python3 tests/test_lsp.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import mock_data  # noqa: E402
from csg.cli import cmd_index  # noqa: E402
from csg.graphdb import GraphDB  # noqa: E402
from csg.lsp_server import LspState, _word_at  # noqa: E402

PASS = 0


def check(name, cond, detail=""):
    global PASS
    assert cond, f"FAIL {name}: {detail}"
    PASS += 1
    print(f"  ok  {name}")


def main() -> None:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="csg_lsp_"))
    mock = tmp / "mock"
    mock_data.generate(str(mock))
    db_path = tmp / "graph.db"
    ns = type("NS", (), {})()
    ns.idir = ns.coverity_home = None
    ns.db = str(db_path)
    ns.mock = str(mock)
    ns.ast_regex = "^parse_packet$"
    ns.ast_limit = 10
    cmd_index(ns)

    st = LspState(GraphDB(str(db_path)))
    st.on_initialize({"rootUri": None})
    uri = "file:///proj/src/telemetry/packet.c"
    text = (
        "\n"  # line 0 空行（0-based 对齐 LSP）
        "static table[256];\n"                       # line 1
        "int parse_packet(const uint8_t *frame) {\n"  # line 2
        "    if (!crc32_verify(frame)) return 0;\n"   # line 3
        "    packet_t *hdr = decode_header(frame);\n" # line 4
        "    return hdr->len;\n"                      # line 5
        "}\n"
    )
    st.on_did_open({"textDocument": {"uri": uri, "text": text}})

    check("word_at 提取", _word_at(text, 3, 10) == "crc32_verify", _word_at(text, 3, 10))

    # definition: decode_header -> packet.c:70
    loc = st.on_definition({"textDocument": {"uri": uri},
                            "position": {"line": 4, "character": 22}})
    check("definition 跳转 decode_header", loc and "packet.c" in loc["uri"] and loc["range"]["start"]["line"] == 69, str(loc))

    # references: crc32_verify 的引用方含 parse_packet / crc32_append
    refs = st.on_references({"textDocument": {"uri": uri},
                             "position": {"line": 3, "character": 10}}) or []
    ref_files = [r["uri"] for r in refs]
    check("references 含自身定义", any("packet.c" in u for u in ref_files), str(refs))
    check("references 含调用者 parse_packet",
          any(r["range"]["start"]["line"] == 87 for r in refs), str(refs))

    # hover
    hv = st.on_hover({"textDocument": {"uri": uri}, "position": {"line": 3, "character": 10}})
    md = hv["contents"]["value"]
    check("hover 实体信息", "crc32_verify" in md and "Green Hills" in md, md)
    check("hover 缺陷计数", "Coverity 缺陷: 2" in md, md)

    # call hierarchy
    items = st.on_prepare_call_hierarchy({"textDocument": {"uri": uri},
                                          "position": {"line": 3, "character": 10}})
    check("prepareCallHierarchy", items and items[0]["name"] == "crc32_verify")
    incoming = st._callers_of(items[0])
    check("incomingCalls 调用者", {c["from"]["name"] for c in incoming} == {"parse_packet"})
    outgoing = st._callees_of({"name": "parse_packet"})
    check("outgoingCalls parse_packet", {c["name"] for c in outgoing} == {"crc32_verify", "decode_header"})

    # diagnostics（didOpen 返回）
    diag = st._diagnostics(uri)
    check("publishDiagnostics 数量", len(diag["diagnostics"]) == 2, str(diag))
    first = {d["code"]: d for d in diag["diagnostics"]}[1001]
    check("诊断含 CID 与 checker", first["source"] == "coverity:NULL_RETURNS" and first["code"] == 1001)

    # didChange 后 diagnostics 仍可用
    st.on_did_change({"textDocument": {"uri": uri}, "contentChanges": [{"text": text}]})
    check("didChange 缓存更新", len(st._diagnostics(uri)["diagnostics"]) == 2)

    # ===== 新增能力：大纲/全局符号/补全/签名/声明 =====
    syms = st.on_document_symbol({"textDocument": {"uri": uri}})
    check("documentSymbol 大纲(5实体)", {x["name"] for x in syms} ==
          {"parse_packet", "crc32_verify", "crc32_table_lookup", "decode_header", "g_packet_buffer"}, str(syms))
    check("documentSymbol kind", all(x["kind"] in (12, 13) for x in syms))

    ws = st.on_workspace_symbol({"query": "crc32"})
    check("workspaceSymbol 全局搜索", {x["name"] for x in ws} == {"crc32_verify", "crc32_table_lookup", "crc32_append"}, str(ws))

    comp = st.on_completion({"textDocument": {"uri": uri}, "position": {"line": 3, "character": 10}})
    # 光标在 crc32_verify 词内 → 前缀补全命中 crc32 系
    check("completion 前缀补全", {c["label"] for c in comp} >= {"crc32_verify"}, str(comp))
    resolved = st.on_completion_resolve(comp[0])
    check("completionResolve 带位置详情", ":" in resolved.get("detail", "")
          and "编译器" in resolved.get("documentation", ""), str(resolved))

    sig_text = "    parse_packet(frame\n"
    import csg.lsp_server as lspmod; lspmod._DOCS[uri] = sig_text
    sig = st.on_signature_help({"textDocument": {"uri": uri}, "position": {"line": 0, "character": 17}})
    check("signatureHelp AST 签名", sig and "parse_packet" in sig["signatures"][0]["label"]
          and "const uint8_t *" in sig["signatures"][0]["label"], str(sig))
    sig2 = st.on_signature_help({"textDocument": {"uri": uri}, "position": {"line": 0, "character": 2}})
    check("signatureHelp 无函数返回 None", sig2 is None)

    import csg.lsp_server as lspmod2; lspmod2._DOCS[uri] = text  # 恢复完整文档
    decl = st.on_declaration({"textDocument": {"uri": uri}, "position": {"line": 3, "character": 10}})
    check("declaration 跳转 crc32_verify@54", decl and "packet.c" in decl["uri"]
          and decl["range"]["start"]["line"] == 54, str(decl))

    print(f"\n全部通过: {PASS} 项检查")


if __name__ == "__main__":
    main()
