"""Coverity CLI 封装层。

真实模式：调用 cov-manage-emit / cov-format-errors（需 COVERITY_HOME 与许可）。
模拟模式：CSG_COV_MOCK=<mock_idir 目录> 时使用预生成的样例输出，
用于无 Coverity 环境下的开发与测试。

真实输出格式可能随 Coverity 版本变化，上线前需在真实 idir 上校准
（见 README 的"格式校准"一节）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CovRunner:
    """cov 命令执行器。mock_dir 提供时使用模拟输出。"""

    coverity_home: str | None = None
    idir: str | None = None
    mock_dir: str | None = None

    @classmethod
    def from_env(cls) -> "CovRunner":
        return cls(
            coverity_home=os.environ.get("COVERITY_HOME"),
            idir=os.environ.get("CSG_IDIR"),
            mock_dir=os.environ.get("CSG_COV_MOCK"),
        )

    @property
    def is_mock(self) -> bool:
        return bool(self.mock_dir)

    def _cov_bin(self, name: str) -> str:
        if self.coverity_home:
            return str(Path(self.coverity_home) / "bin" / name)
        found = shutil.which(name)
        if not found:
            raise RuntimeError(f"找不到 {name}，请设置 COVERITY_HOME 或加入 PATH")
        return found

    def run(self, args: list[str]) -> str:
        if self.is_mock:
            return self._mock_read(args)
        if not self.idir:
            raise RuntimeError("未设置 CSG_IDIR（Coverity 中间目录）")
        cmd = [self._cov_bin(args[0]), "--dir", self.idir] + args[1:]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if out.returncode != 0:
            raise RuntimeError(f"{args[0]} 失败: {out.stderr[:2000]}")
        return out.stdout

    def _mock_read(self, args: list[str]) -> str:
        """按约定读取 mock 目录下的同名输出文件。

        mock 文件命名：
          mock_dir/tus.json               <- cov-manage-emit list (自定义 --json 封装)
          mock_dir/callees.json           <- cov-manage-emit find '.*' --print-callees
          mock_dir/asts/<fn>.json         <- cov-manage-emit find <fn> --print-codexm
          mock_dir/issues.json            <- cov-format-errors --json-output-v10
        """
        base = Path(self.mock_dir)  # type: ignore[arg-type]
        name = args[0]
        if name == "cov-manage-emit":
            if "--print-callees" in args:
                path = base / "callees.json"
            elif "--print-codexm" in args:
                fn = args[args.index("find") + 1].strip("^$")
                path = base / "asts" / f"{fn}.json"
            else:
                path = base / "tus.json"
        elif name == "cov-format-errors":
            path = base / "issues.json"
        else:
            raise RuntimeError(f"mock 模式不支持: {name}")
        if not path.exists():
            raise RuntimeError(f"mock 输出缺失: {path}")
        return path.read_text(encoding="utf-8")


# ---------- 数据模型 ----------


@dataclass
class TU:
    tu_id: int
    primary_file: str
    compiler: str
    args: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)


@dataclass
class Entity:
    name: str
    kind: str                 # function / variable / type
    file: str
    line: int
    definition: str = ""      # "file:line"
    callees: list[str] = field(default_factory=list)


@dataclass
class Issue:
    cid: int
    checker: str
    severity: str
    function: str
    file: str
    line: int
    message: str


# ---------- 解析层（真实/模拟输出 -> 数据模型）----------


def parse_tus(raw: str) -> list[TU]:
    """解析 cov-manage-emit list 输出。支持自定义 JSON 适配格式。"""
    data = json.loads(raw)
    tus = []
    for e in data.get("translation_units", []):
        tus.append(
            TU(
                tu_id=int(e["id"]),
                primary_file=e.get("primary_file", ""),
                compiler=e.get("compiler", ""),
                args=e.get("args", []),
                source_files=e.get("source_files", []),
            )
        )
    return tus


def parse_entities(raw: str) -> list[Entity]:
    """解析 find '.*'（可含 --print-callees）的 JSON 适配输出。"""
    data = json.loads(raw)
    ents = []
    for e in data.get("entities", []):
        ents.append(
            Entity(
                name=e["name"],
                kind=e.get("kind", "function"),
                file=e.get("file", ""),
                line=int(e.get("line", 0)),
                definition=e.get("definition", ""),
                callees=e.get("callees", []),
            )
        )
    return ents


def parse_issues(raw: str) -> list[Issue]:
    """解析 cov-format-errors --json-output-v10 输出。"""
    data = json.loads(raw)
    issues = []
    for it in data.get("issues", []):
        # v10: file 是事件栈，第一个事件为主位置
        events = it.get("file", []) or []
        main = events[0] if events else {}
        issues.append(
            Issue(
                cid=int(it.get("cid", 0)),
                checker=it.get("checkerName", it.get("checker", "")),
                severity=it.get("severity", "Unspecified"),
                function=it.get("function", {}).get("name", "") if isinstance(it.get("function"), dict) else str(it.get("function", "")),
                file=main.get("file", it.get("mainEventFile", "")),
                line=int(main.get("line", it.get("mainEventLine", 0))),
                message=main.get("description", it.get("message", "")),
            )
        )
    return issues


def parse_ast(raw: str) -> dict:
    """函数级 AST（CodeXM 模型），原样透传 JSON。"""
    return json.loads(raw)


# ---------- 真实文本输出解析（cov-manage-emit 原生格式，已用 cJSON 实测校准）----------
#
# list 格式:
#   Translation unit:
#   1 -> /abs/path/cJSON.c
#
# find [--print-callees] 格式:
#   Matching function: cJSON_ParseWithOpts
#    declared at:
#      /abs/path/cJSON.c:1088:23-/abs/path/cJSON.c:1088:41
#    defined in TU 1 with row 69
#   Calls:
#    Call to: cJSON_ParseWithLengthOpts
#      declared at:
#        /abs/path/cJSON.c:1104:23-...

import re as _re

_TU_RE = _re.compile(r"^\s*(\d+)\s*->\s*(.+)$", _re.M)
_ENT_RE = _re.compile(
    r"Matching (\w+): (\S+)\n declared at:\n\s+([^:\n]+):(\d+):\d+",
    _re.M,
)
_CALL_RE = _re.compile(r"Call to: (\S+)\n\s+declared at:\n\s+([^:\n]+):(\d+):", _re.M)


def parse_tus_text(raw: str) -> list[TU]:
    return [TU(tu_id=int(m[0]), primary_file=m[1].strip(), compiler="", args=[], source_files=[])
            for m in _TU_RE.findall(raw)]


def parse_entities_text(raw: str) -> list[Entity]:
    """按 'Matching' 块切分，块内再抓 Call to。真实文本格式，无 JSON。"""
    entities: list[Entity] = []
    blocks = raw.split("Matching ")[1:]
    for blk in blocks:
        m = _re.match(r"(\w+): (\S+)\n declared at:\n\s+([^:\n]+):(\d+):", blk)
        if not m:
            continue
        kind, name, file, line = m.group(1), m.group(2), m.group(3), int(m.group(4))
        callees = [(c[0], c[1], int(c[2])) for c in _CALL_RE.findall(blk)]
        # 记录 callee 的真实定义位置（去重后合并到实体表）
        entities.append(Entity(
            name=name, kind=kind, file=file, line=line,
            definition=f"{file}:{line}",
            callees=sorted({c[0] for c in callees}),
        ))
        # callee 位置信息单独返回不了，通过附加实体兜底：
        for cname, cfile, cline in callees:
            if cname != name and not any(e.name == cname for e in entities):
                entities.append(Entity(name=cname, kind="function", file=cfile, line=cline,
                                       definition=f"{cfile}:{cline}", callees=[]))
    return entities
