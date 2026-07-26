#!/bin/bash
# 波次采集驱动：对抗盖德 IP 级限流。
# 每波：逐品牌检查存量，不足目标数才调用采集器；品牌间 sleep 45-75s（随机）。
# 波间冷却 8 分钟。已有 JSON 自动跳过（采集器断点续采），失败的下波重试。
# 用法：bash data/tools/collect_waves.sh [目标每品牌产品数=20] [最大波数=8]

TARGET=${1:-20}
MAX_WAVES=${2:-8}
ROOT=/root/workspace/olaiya
BRANDS=$ROOT/data/tools/brands.txt
RAW=$ROOT/data/raw/guidechem
PY=/tmp/pwenv/bin/python

for ((wave=1; wave<=MAX_WAVES; wave++)); do
    echo "================ 第 $wave 波 $(date '+%H:%M:%S') ================"
    all_done=1
    while IFS= read -r brand; do
        [ -z "$brand" ] && continue
        count=$(ls "$RAW/$brand"/*.json 2>/dev/null | wc -l)
        if [ "$count" -ge "$TARGET" ]; then
            echo "[$brand] 已有 $count 个，达标跳过"
            continue
        fi
        all_done=0
        echo "[$brand] 已有 $count/$TARGET，开始采集 $(date '+%H:%M:%S')"
        (cd "$ROOT" && "$PY" data/tools/collect_guidechem.py --brand "$brand" --pages 2 --limit 0)
        sleep $((45 + RANDOM % 30))
    done < "$BRANDS"
    [ "$all_done" -eq 1 ] && { echo "全部品牌达标，结束。"; break; }
    [ "$wave" -lt "$MAX_WAVES" ] && { echo "---- 波间冷却 8 分钟 ----"; sleep 480; }
done
echo "================ 采集驱动结束 $(date '+%H:%M:%S') ================"
for d in "$RAW"/*/; do
    b=$(basename "$d")
    echo "$b: $(ls "$d"*.json 2>/dev/null | wc -l)"
done