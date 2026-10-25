#!/usr/bin/env bash
# calibrate.sh — 在装有 cov-analysis 的机器上运行，导出真实输出供 csg 解析层校准
# 用法: ./calibrate.sh <idir路径> [Coverity工具bin目录]
set -euo pipefail
IDIR="${1:?用法: calibrate.sh <idir> [cov-bin]}"
BIN="${2:-}"
[ -n "$BIN" ] && PATH="$BIN:$PATH"
OUT="calibration_$(date +%Y%m%d)"
mkdir -p "$OUT/asts"

echo "[1/4] TU 列表（含编译参数）..."
cov-manage-emit --dir "$IDIR" list > "$OUT/tu_list.txt" 2>&1 || true
cov-manage-emit --dir "$IDIR" list --json-output > "$OUT/tu_list.json" 2>&1 || true

echo "[2/4] 实体 + 调用边..."
cov-manage-emit --dir "$IDIR" find '.*' > "$OUT/entities.txt" 2>&1 || true
cov-manage-emit --dir "$IDIR" find '.*' --print-callees > "$OUT/callees.txt" 2>&1 || true
cov-manage-emit --dir "$IDIR" find '.*' --print-callees --json-output > "$OUT/callees.json" 2>&1 || true

echo "[3/4] 样例函数 AST（取3个函数）..."
FUNCS=$(grep -oE '[a-zA-Z_]\w*' "$OUT/entities.txt" | sort -u | head -3 || true)
for fn in $FUNCS; do
  cov-manage-emit --dir "$IDIR" find "^$fn$" --print-codexm > "$OUT/asts/$fn.json" 2>&1 || true
done

echo "[4/4] 缺陷导出（需先 cov-analyze；未分析则为空）..."
cov-format-errors --dir "$IDIR" --json-output-v10 > "$OUT/issues.json" 2>&1 || true

echo "完成。将 $OUT/ 目录整体回传给开发侧即可校准 src/csg/coverity.py 解析层。"
tar czf "$OUT.tar.gz" "$OUT"
echo "打包: $OUT.tar.gz"
