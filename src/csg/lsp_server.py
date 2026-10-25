"""csg-ls：基于 CSG 图库的语言服务器（无第三方 LSP 框架，手写 JSON-RPC/stdio）。

为 VSCode（及任何 LSP 客户端）提供编译器级的嵌入式 C/C++ 语义能力：
  textDocument/definition      定义跳转（编译器验证）
  textDocument/references      查找引用（调用者/被调者位置）
  textDocument/hover           悬停：实体信息 + 缺陷数 + 编译器
  textDocument/prepareCallHierarchy + incoming/outgoing   调用层级
  textDocument/didOpen         发布该文件 Coverity 缺陷诊断

启动: CSG_DB=/abs/graph.db python3 -m csg.lsp_server
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .graphdb import GraphDB

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

VERSION = "0.1.0"
SERVER_CAPS = {
    "textDocumentSync": 1,  # full
    "definitionProvider": True,
    "referencesProvider": True,
    "hoverProvider": True,
    "callHierarchyProvider": True,
    "declarationProvider": True,
    "documentSymbolProvider": True,
    "workspaceSymbolProvider": True,
    "completionProvider": {"triggerCharacters": [":", ">", "_", "."], "resolveProvider": True},
    "signatureHelpProvider": {"triggerCharacters": ["("]},
}

LSP_KIND = {"function": 12, "variable": 13, "type": 23}  # Function/Variable/Struct

# 客户端打开的文档缓存（didOpen/didChange 全量同步）
_DOCS: dict[str, str] = {}


# ---------- 位置解析 ----------


def _word_at(text: str, line: int, character: int) -> str | None:
    lines = text.split("\n")
    if line >= len(lines):
        return None
    for m in WORD_RE.finditer(lines[line]):
        if m.start() <= character <= m.end():
            return m.group()
    return None


def _loc(uri_prefix: str, row: tuple) -> dict:
    """entities 行 -> LSP Location（词首位置）。"""
    name, _kind, file, line, _defn = row
    return {
        "uri": uri_prefix + str(Path(file).resolve()),
        "range": {
            "start": {"line": max(line - 1, 0), "character": 0},
            "end": {"line": max(line - 1, 0), "character": len(name)},
        },
    }


def _entity_location(db: GraphDB, name: str, uri_prefix: str) -> dict | None:
    rows = db.get_definition(name)
    if not rows:
        return None
    return _loc(uri_prefix, (rows[0]["name"], rows[0]["kind"], rows[0]["file"],
                             rows[0]["line"], rows[0]["definition"]))


# ---------- LSP 处理器（与传输无关，便于单测） ----------


class LspState:
    def __init__(self, db: GraphDB):
        self.db = db
        self.root_uri = ""

    # initialize
    def on_initialize(self, params: dict) -> dict:
        self.root_uri = params.get("rootUri") or ""
        return {"capabilities": SERVER_CAPS, "serverInfo": {"name": "csg-ls", "version": VERSION}}

    def on_did_open(self, params: dict) -> dict | None:
        doc = params["textDocument"]
        _DOCS[doc["uri"]] = doc.get("text", "")
        return self._diagnostics(doc["uri"])

    def on_did_change(self, params: dict) -> dict | None:
        doc = params["textDocument"]
        changes = params.get("contentChanges") or []
        if changes:
            _DOCS[doc["uri"]] = changes[-1].get("text", "")
        return self._diagnostics(doc["uri"])

    def _diagnostics(self, uri: str) -> dict | None:
        file = _uri_to_path(uri)
        issues = self.db.file_issues(file)
        if not issues:
            # 图库存相对路径，按文件名回退匹配
            issues = self.db.file_issues(Path(file).name)
        if not issues:
            return {"uri": uri, "diagnostics": []}
        return {
            "uri": uri,
            "diagnostics": [
                {
                    "range": {
                        "start": {"line": max(i["line"] - 1, 0), "character": 0},
                        "end": {"line": max(i["line"] - 1, 0), "character": 200},
                    },
                    "severity": 1 if i["severity"] in ("Major", "Critical") else 2,
                    "source": f"coverity:{i['checker']}",
                    "message": f"[CID {i['cid']}] {i['message']}",
                    "code": i["cid"],
                }
                for i in issues
            ],
        }

    # definition
    def on_definition(self, params: dict) -> Any:
        pos = params["position"]
        word = _word_at(_DOCS.get(params["textDocument"]["uri"], ""), pos["line"], pos["character"])
        if not word:
            return None
        return _entity_location(self.db, word, "file://")

    # references
    def on_references(self, params: dict) -> list | None:
        pos = params["position"]
        word = _word_at(_DOCS.get(params["textDocument"]["uri"], ""), pos["line"], pos["character"])
        if not word:
            return None
        out: list[dict] = []
        own = self.db.get_definition(word)
        if own:
            out.append(_loc("file://", (own[0]["name"], own[0]["kind"], own[0]["file"],
                                       own[0]["line"], own[0]["definition"])))
        # 引用方：调用它的函数定义处
        for caller in self.db.what_calls(word):
            rows = self.db.get_definition(caller)
            if rows:
                out.append(_loc("file://", (rows[0]["name"], rows[0]["kind"], rows[0]["file"],
                                            rows[0]["line"], rows[0]["definition"])))
        return out

    # hover
    def on_hover(self, params: dict) -> dict | None:
        pos = params["position"]
        word = _word_at(_DOCS.get(params["textDocument"]["uri"], ""), pos["line"], pos["character"])
        if not word:
            return None
        rows = self.db.get_definition(word)
        if not rows:
            return None
        e = rows[0]
        issue_cnt = len(self.db.file_issues(e["file"]))
        tu = next((t for t in self.db.list_tus()
                   if t["primary_file"].endswith(e["file"].split("/")[-1])), None)
        compiler = tu["compiler"] if tu else "unknown"
        md = (
            f"**{e['name']}** `{e['kind']}`  \n"
            f"📍 `{e['file']}:{e['line']}`  \n"
            f"🛠 编译器: {compiler}  \n"
            f"🐞 本文件 Coverity 缺陷: {issue_cnt}"
        )
        return {"contents": {"kind": "markdown", "value": md}}

    # declaration -> 与 definition 同源（CSG 无独立声明数据时跳转到定义）
    def on_declaration(self, params: dict) -> Any:
        return self.on_definition(params)

    # document symbols（大纲视图）
    def on_document_symbol(self, params: dict) -> list:
        file = _uri_to_path(params["textDocument"]["uri"])
        ents = self.db.file_entities(file) or self.db.file_entities(Path(file).name)
        syms = []
        for e in ents:
            line = max(e["line"] - 1, 0)
            rng = {"start": {"line": line, "character": 0},
                   "end": {"line": line, "character": len(e["name"])}}
            syms.append({"name": e["name"], "kind": LSP_KIND.get(e["kind"], 13),
                         "range": rng, "selectionRange": rng})
        return syms

    # workspace symbols（Ctrl+T 全局符号搜索）
    def on_workspace_symbol(self, params: dict) -> list:
        q = params.get("query", "")
        out = []
        for e in self.db.search_entities(q + "*" if q else q, 200):
            line = max(e["line"] - 1, 0)
            rng = {"start": {"line": line, "character": 0},
                   "end": {"line": line, "character": len(e["name"])}}
            out.append({"name": e["name"], "kind": LSP_KIND.get(e["kind"], 13),
                        "location": {"uri": "file://" + str(Path(e["file"]).resolve()), "range": rng}})
        return out

    # completion（项目级符号补全）
    def on_completion(self, params: dict) -> list:
        doc = params["textDocument"]["uri"]; pos = params["position"]
        text = _DOCS.get(doc, "")
        line = text.split("\n")[pos["line"]] if pos["line"] < len(text.split("\n")) else ""
        prefix_m = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", line[:pos["character"]])
        prefix = prefix_m.group() if prefix_m else ""
        if not prefix:
            return []
        items = []
        for e in self.db.search_entities(prefix + "*", 50):
            items.append({
                "label": e["name"],
                "kind": LSP_KIND.get(e["kind"], 1),
                "data": {"name": e["name"]},
                "sortText": ("0" if e["name"] == prefix else "1") + e["name"],
            })
        return items

    def on_completion_resolve(self, item: dict) -> dict:
        rows = self.db.get_definition(item["label"])
        if rows:
            e = rows[0]
            item["detail"] = f"{e['kind']} — {e['file']}:{e['line']}"
            tu = next((t for t in self.db.list_tus()
                       if t["primary_file"].endswith(e["file"].split("/")[-1])), None)
            item["documentation"] = f"编译器: {tu['compiler']}" if tu else ""
        return item

    # signature help（基于已索引的 CodeXM AST）
    def on_signature_help(self, params: dict) -> dict | None:
        pos = params["position"]
        text = _DOCS.get(params["textDocument"]["uri"], "")
        lines = text.split("\n")
        if pos["line"] >= len(lines):
            return None
        before = lines[pos["line"]][:pos["character"]]
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\([^()]*$", before)
        if not m:
            return None
        ast = self.db.get_ast(m.group(1))
        if not ast:
            return None
        params_list = [p.get("type", "?") + " " + p.get("identifier", "?")
                       for p in ast.get("formalParameterList", [])]
        label = f"{ast.get('returnType', '')} {ast['name']}({', '.join(params_list)})"
        return {"signatures": [{"label": label, "parameters": [
                    {"label": [label.index(p), label.index(p) + len(p)]} for p in params_list
                ]}],
                "activeSignature": 0, "activeParameter": 0}

    # call hierarchy
    def on_prepare_call_hierarchy(self, params: dict) -> list | None:
        pos = params["position"]
        word = _word_at(_DOCS.get(params["textDocument"]["uri"], ""), pos["line"], pos["character"])
        if not word:
            return None
        loc = _entity_location(self.db, word, "file://")
        if not loc:
            return None
        return [{"name": word, "kind": 12, "uri": loc["uri"], "range": loc["range"],
                 "selectionRange": loc["range"]}]

    def _callers_of(self, item: dict) -> list[dict]:
        out = []
        for caller in self.db.what_calls(item["name"]):
            loc = _entity_location(self.db, caller, "file://")
            if loc:
                out.append({"from": {"name": caller, "kind": 12, "uri": loc["uri"],
                                     "range": loc["range"], "selectionRange": loc["range"]},
                            "fromRanges": [loc["range"]]})
        return out

    def _callees_of(self, item: dict) -> list[dict]:
        out = []
        for callee in self.db.called_by(item["name"]):
            loc = _entity_location(self.db, callee, "file://")
            if loc:
                out.append({"name": callee, "kind": 12, "uri": loc["uri"],
                            "range": loc["range"], "selectionRange": loc["range"],
                            "fromRanges": []})
        return out


def _uri_to_path(uri: str) -> str:
    return uri[7:] if uri.startswith("file://") else uri


# ---------- stdio JSON-RPC 传输 ----------


def _read_msg() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length == 0:
        return None
    body = sys.stdin.read(length)
    return json.loads(body)


def _send(msg: dict) -> None:
    data = json.dumps(msg, ensure_ascii=False)
    sys.stdout.write(f"Content-Length: {len(data.encode())}\r\n\r\n{data}")
    sys.stdout.flush()


def serve(db_path: str) -> None:
    state = LspState(GraphDB(db_path))
    handlers = {
        "initialize": state.on_initialize,
        "textDocument/didOpen": state.on_did_open,
        "textDocument/didChange": state.on_did_change,
        "textDocument/definition": state.on_definition,
        "textDocument/references": state.on_references,
        "textDocument/hover": state.on_hover,
        "textDocument/declaration": state.on_declaration,
        "textDocument/documentSymbol": state.on_document_symbol,
        "workspace/symbol": state.on_workspace_symbol,
        "textDocument/completion": state.on_completion,
        "completionItem/resolve": state.on_completion_resolve,
        "textDocument/signatureHelp": state.on_signature_help,
        "textDocument/prepareCallHierarchy": state.on_prepare_call_hierarchy,
        "callHierarchy/incomingCalls": lambda p: state._callers_of(p["item"]),
        "callHierarchy/outgoingCalls": lambda p: state._callees_of(p["item"]),
    }
    while True:
        msg = _read_msg()
        if msg is None:
            break
        method, params, msg_id = msg.get("method"), msg.get("params", {}), msg.get("id")
        if method == "shutdown":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": None})
            continue
        if method == "exit":
            break
        h = handlers.get(method)
        if h is None:
            if msg_id is not None:
                _send({"jsonrpc": "2.0", "id": msg_id,
                       "error": {"code": -32601, "message": f"未实现: {method}"}})
            continue
        result = h(params)
        if msg_id is not None:
            _send({"jsonrpc": "2.0", "id": msg_id, "result": result})
        elif method in ("textDocument/didOpen", "textDocument/didChange") and result:
            _send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                   "params": result})


def main() -> None:
    import os
    db = os.environ.get("CSG_DB")
    if not db:
        sys.stderr.write("csg-ls: 未设置 CSG_DB\n")
        sys.exit(1)
    serve(db)


if __name__ == "__main__":
    main()
