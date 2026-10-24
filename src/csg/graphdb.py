"""SQLite 图库：TU / 实体 / 调用边 / 缺陷 + FTS5 + 反向调用索引。"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .coverity import Entity, Issue, TU

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tus (
    tu_id INTEGER PRIMARY KEY, primary_file TEXT, compiler TEXT, args TEXT
);
CREATE TABLE IF NOT EXISTS tu_sources (tu_id INTEGER, source_file TEXT);
CREATE INDEX IF NOT EXISTS idx_tus_file ON tus(primary_file);
CREATE TABLE IF NOT EXISTS entities (
    name TEXT, kind TEXT, file TEXT, line INTEGER, definition TEXT,
    PRIMARY KEY (name, file, line)
);
CREATE TABLE IF NOT EXISTS callees (caller TEXT, callee TEXT);
CREATE INDEX IF NOT EXISTS idx_callees_caller ON callees(caller);
CREATE INDEX IF NOT EXISTS idx_callees_callee ON callees(callee);
CREATE TABLE IF NOT EXISTS issues (
    cid INTEGER PRIMARY KEY, checker TEXT, severity TEXT,
    function TEXT, file TEXT, line INTEGER, message TEXT
);
CREATE INDEX IF NOT EXISTS idx_issues_file ON issues(file);
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(name, file, kind, content='entities', content_rowid='rowid');
CREATE TABLE IF NOT EXISTS asts (name TEXT PRIMARY KEY, ast TEXT);
"""


class GraphDB:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)

    # ---------- 写入（索引阶段） ----------

    def build(self, tus: list[TU], entities: list[Entity], issues: list[Issue]) -> dict:
        c = self.conn
        c.executemany(
            "INSERT OR REPLACE INTO tus VALUES (?,?,?,?)",
            [(t.tu_id, t.primary_file, t.compiler, json.dumps(t.args)) for t in tus],
        )
        c.executemany(
            "INSERT INTO tu_sources VALUES (?,?)",
            [(t.tu_id, s) for t in tus for s in t.source_files],
        )
        c.executemany(
            "INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?)",
            [(e.name, e.kind, e.file, e.line, e.definition) for e in entities],
        )
        c.executemany(
            "INSERT OR REPLACE INTO callees VALUES (?,?)",
            [(e.name, callee) for e in entities for callee in e.callees],
        )
        c.executemany(
            "INSERT OR REPLACE INTO issues VALUES (?,?,?,?,?,?,?)",
            [(i.cid, i.checker, i.severity, i.function, i.file, i.line, i.message) for i in issues],
        )
        c.execute(
            "INSERT INTO entities_fts(entities_fts) VALUES('rebuild')"
        )
        c.execute(
            "INSERT OR REPLACE INTO meta VALUES ('built_at', ?)",
            (str(int(time.time())),),
        )
        c.execute("INSERT OR REPLACE INTO meta VALUES ('version', '1')")
        c.commit()
        return self.stats()

    def store_ast(self, fn: str, ast: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO asts VALUES (?,?)", (fn, json.dumps(ast))
        )
        self.conn.commit()

    # ---------- 查询（MCP 阶段） ----------

    def list_tus(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tu_id, primary_file, compiler, args FROM tus ORDER BY primary_file"
        ).fetchall()
        return [
            {"tu_id": r[0], "primary_file": r[1], "compiler": r[2], "args": json.loads(r[3])}
            for r in rows
        ]

    def _entity_row(self, r: tuple) -> dict:
        return {"name": r[0], "kind": r[1], "file": r[2], "line": r[3], "definition": r[4]}

    def search_entities(self, query: str, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT e.name, e.kind, e.file, e.line, e.definition FROM entities_fts f "
            "JOIN entities e ON e.rowid = f.rowid WHERE entities_fts MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
        return [self._entity_row(r) for r in rows]

    def file_entities(self, file: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, kind, file, line, definition FROM entities "
            "WHERE file LIKE ? ORDER BY line",
            (f"%{file}",),
        ).fetchall()
        return [self._entity_row(r) for r in rows]

    def get_definition(self, name: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, kind, file, line, definition FROM entities WHERE name = ?", (name,)
        ).fetchall()
        return [self._entity_row(r) for r in rows]

    def what_calls(self, fn: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT caller FROM callees WHERE callee = ? ORDER BY caller", (fn,)
        )]

    def called_by(self, fn: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT callee FROM callees WHERE caller = ? ORDER BY callee", (fn,)
        )]

    def blast_radius(self, fn: str, max_depth: int = 5) -> dict:
        """反向传播：谁受 fn 变更影响（BFS on caller edges）。"""
        affected: dict[str, int] = {}
        frontier, depth = [fn], 1
        while frontier and depth <= max_depth:
            nxt: list[str] = []
            for node in frontier:
                for caller in self.what_calls(node):
                    if caller not in affected and caller != fn:
                        affected[caller] = depth
                        nxt.append(caller)
            frontier, depth = nxt, depth + 1
        by_depth: dict[int, list[str]] = {}
        for name, d in affected.items():
            by_depth.setdefault(d, []).append(name)
        return {"source": fn, "total_affected": len(affected), "by_depth": by_depth}

    def call_path(self, a: str, b: str, max_depth: int = 8) -> list[str] | None:
        """a -> b 正向 BFS 最短调用链。"""
        from collections import deque

        if a == b:
            return [a]
        q: deque[tuple[str, list[str]]] = deque([(a, [a])])
        visited = {a}
        while q:
            node, path = q.popleft()
            if len(path) > max_depth:
                continue
            for callee in self.called_by(node):
                if callee == b:
                    return path + [b]
                if callee not in visited:
                    visited.add(callee)
                    q.append((callee, path + [callee]))
        return None

    def file_issues(self, file: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT cid, checker, severity, function, file, line, message "
            "FROM issues WHERE file LIKE ? ORDER BY line",
            (f"%{file}",),
        ).fetchall()
        cols = ["cid", "checker", "severity", "function", "file", "line", "message"]
        return [dict(zip(cols, r)) for r in rows]

    def get_ast(self, fn: str) -> dict | None:
        row = self.conn.execute("SELECT ast FROM asts WHERE name = ?", (fn,)).fetchone()
        return json.loads(row[0]) if row else None

    def stats(self) -> dict:
        def count(sql: str) -> int:
            return self.conn.execute(sql).fetchone()[0]

        return {
            "tus": count("SELECT COUNT(*) FROM tus"),
            "entities": count("SELECT COUNT(*) FROM entities"),
            "call_edges": count("SELECT COUNT(*) FROM callees"),
            "issues": count("SELECT COUNT(*) FROM issues"),
            "asts": count("SELECT COUNT(*) FROM asts"),
            "built_at": dict(self.conn.execute("SELECT key, value FROM meta")).get("built_at"),
        }
