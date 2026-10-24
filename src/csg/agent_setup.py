"""为 Claude Code / Codex CLI / OpenCode 自动生成 MCP 接入配置。

用法: python -m csg.agent_setup --db /path/to/graph.db [--scope user|project] [--only claude,codex,opencode]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

CLIENTS = ["claude", "codex", "opencode"]


def _csg_cmd(db: str) -> dict:
    return {
        "command": "csg-mcp",
        "args": [],
        "env": {"CSG_DB": os.path.abspath(db)},
    }


def setup_claude(db: str, scope: str) -> str:
    """Claude Code：project 用 .mcp.json，user 用 ~/.claude.json 的 mcpServers。"""
    cfg = _csg_cmd(db)
    if scope == "project":
        p = Path(".mcp.json")
        data = json.loads(p.read_text()) if p.exists() else {}
        data.setdefault("mcpServers", {})["csg"] = cfg
    else:
        p = Path.home() / ".claude.json"
        data = json.loads(p.read_text()) if p.exists() else {}
        data.setdefault("mcpServers", {})["csg"] = cfg
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return str(p)


def setup_codex(db: str, scope: str) -> str:
    """Codex CLI：~/.codex/config.toml 的 [mcp_servers.csg]。"""
    p = Path.home() / ".codex" / "config.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text() if p.exists() else ""
    if "[mcp_servers.csg]" not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += (
            "\n[mcp_servers.csg]\n"
            'command = "csg-mcp"\n'
            "args = []\n\n"
            "[mcp_servers.csg.env]\n"
            f'CSG_DB = "{os.path.abspath(db)}"\n'
        )
        p.write_text(text)
    return str(p)


def setup_opencode(db: str, scope: str) -> str:
    """OpenCode：~/.config/opencode/opencode.json 的 mcp 段。"""
    p = Path.home() / ".config" / "opencode" / "opencode.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text()) if p.exists() else {}
    data.setdefault("mcp", {})["csg"] = {
        "type": "local",
        "command": ["csg-mcp"],
        "environment": {"CSG_DB": os.path.abspath(db)},
        "enabled": True,
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return str(p)


def main() -> None:
    ap = argparse.ArgumentParser(prog="csg-agent-setup")
    ap.add_argument("--db", required=True, help="csg-index 产出的 SQLite 图库路径")
    ap.add_argument("--scope", choices=["user", "project"], default="user")
    ap.add_argument("--only", default="claude,codex,opencode")
    args = ap.parse_args()

    for name in args.only.split(","):
        name = name.strip().lower()
        if name not in CLIENTS:
            print(f"跳过未知客户端: {name}")
            continue
        path = globals()[f"setup_{name}"](args.db, args.scope)
        print(f"[csg] {name} 配置已写入: {path}")


if __name__ == "__main__":
    main()
