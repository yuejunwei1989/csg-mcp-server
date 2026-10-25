"""cov_sim.py — cov-manage-emit 模拟器（预演/回归用，非 Coverity 替代品）。

从真实构建产物生成与 csg 适配格式一致的 mock 输出：
  compile_commands.json (bear)  -> tus.json      （TU + 编译参数 + 头文件依赖 via gcc -MM）
  真实源码                      -> callees.json  （函数/定义行 + 调用边 via GNU cflow）
  （缺陷 issues.json 需真实 cov-analyze，模拟为空）

用法: python3 tests/cov_sim.py <项目根目录> <输出mock目录> [compile_commands.json路径]
"""
import json
import re
import subprocess
import sys
from pathlib import Path


def gen_tus(proj: Path, cdb: list) -> dict:
    tus = []
    for i, e in enumerate(cdb, 1):
        args = e.get("arguments") or e.get("command").split()
        srcs = [a for a in args if a.endswith((".c", ".cc", ".cpp", ".cxx"))]
        primary = srcs[0] if srcs else ""
        # gcc -MM 获取头文件依赖（真实"参与编译的文件"）
        try:
            mm = subprocess.run(
                ["gcc", "-MM"] + [a for a in args[1:] if not a.startswith("-o") and not a.endswith(".o")],
                cwd=e.get("directory", str(proj)), capture_output=True, text=True, check=False)
            deps = re.findall(r"[\w/.\-]+\.(?:h|hpp)", mm.stdout)
        except Exception:
            deps = []
        tus.append({
            "id": i, "primary_file": primary,
            "compiler": args[0],
            "args": args[1:],
            "source_files": sorted(set(srcs) | set(deps)),
        })
    return {"translation_units": tus}


CDEF = re.compile(r"([\w\* ]+?)(\w+)\s*\(", )


def gen_callees(proj: Path, cdb: list) -> dict:
    """用 cflow 建真实调用图。输出行: 缩进=层级, name() <...at file:line>。

    关键：--preprocess 用真实编译参数的 gcc -E 展开源码宏（如 cJSON 的
    CJSON_PUBLIC(x)），否则大量宏包装的函数会丢失——这正是编译器语义的价值。
    """
    # 每个 TU 的预处理参数（-I/-D 等）
    pp_cache: dict[str, str] = {}
    for e in cdb:
        args = e.get("arguments") or e.get("command").split()
        srcs = [a for a in args if a.endswith((".c", ".cc", ".cpp", ".cxx"))]
        pp = " ".join(a for a in args[1:] if a.startswith(("-I", "-D", "-U")) or a in ("-pedantic",))
        for s in srcs:
            pp_cache.setdefault(Path(s).name, pp)

    c_files = sorted(pp_cache)
    funcs: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    for f in c_files:
        cmd = ["cflow", f"--preprocess=gcc -E {pp_cache[f]}", f]
        try:
            out = subprocess.run(cmd, cwd=proj, capture_output=True, text=True, check=False).stdout
        except FileNotFoundError:
            out = ""
        stack: list[str] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            m = re.search(r"(\w+)\(\)\s*<.*?at ([\w./\-]+):(\d+)>", line)
            if not m:
                continue
            name, fname, ln = m.group(1), m.group(2), int(m.group(3))
            if name not in funcs:
                funcs[name] = {"file": fname, "line": ln}
            while len(stack) > indent // 4:
                stack.pop()
            if stack:
                edges.add((stack[-1], name))
            del stack[indent // 4 + 1:]
            stack.append(name)

    entities = []
    for name, info in funcs.items():
        entities.append({
            "name": name, "kind": "function", "file": info["file"], "line": info["line"],
            "definition": f"{info['file']}:{info['line']}",
            "callees": sorted({c for a, c in edges if a == name}),
        })
    return {"entities": entities}


def main():
    proj = Path(sys.argv[1]).resolve()
    outdir = Path(sys.argv[2]); outdir.mkdir(parents=True, exist_ok=True)
    cdb_path = Path(sys.argv[3]) if len(sys.argv) > 3 else proj / "compile_commands.json"
    cdb = json.loads(cdb_path.read_text())

    tus = gen_tus(proj, cdb)
    (outdir / "tus.json").write_text(json.dumps(tus, ensure_ascii=False, indent=1), "utf-8")

    ents = gen_callees(proj, cdb)
    (outdir / "callees.json").write_text(json.dumps(ents, ensure_ascii=False, indent=1), "utf-8")

    (outdir / "issues.json").write_text(json.dumps({"format_version": "1.4", "issues": []}), "utf-8")
    print(f"[cov_sim] TU: {len(tus['translation_units'])}, 函数: {len(ents['entities'])}, "
          f"调用边: {sum(len(e['callees']) for e in ents['entities'])} -> {outdir}")


if __name__ == "__main__":
    main()
