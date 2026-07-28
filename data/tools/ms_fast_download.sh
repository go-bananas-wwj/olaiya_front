#!/bin/bash
# 并行分段下载 modelscope 大文件（绕过代理直连 CDN，分段重试+断点续传）
# 用法: ms_fast_download.sh <modelscope_resolve_url> <output_file> [并发数]
set -u
URL="$1"; OUT="$2"; N="${3:-16}"
CDN=$(curl -s --noproxy '*' -D - -o /dev/null "$URL" | grep -i '^Location:' | sed 's/^[Ll]ocation: //' | tr -d '\r')
if [ -z "$CDN" ]; then echo "no redirect, using direct url"; CDN="$URL"; fi
TOTAL=$(curl -sI --noproxy '*' "$CDN" | grep -i content-length | tr -d '\r' | awk '{print $2}')
echo "size=$TOTAL parts=$N"
TMPD=$(mktemp -d)
echo "tmpdir=$TMPD"

dl_part() {
  local i=$1
  local s=$((i*TOTAL/N)); local e=$(( (i+1)*TOTAL/N - 1 ))
  [ $i -eq $((N-1)) ] && e=$((TOTAL-1))
  local want=$((e-s+1))
  for try in 1 2 3 4 5 6 7 8; do
    local have=0
    [ -f "$TMPD/part.$i" ] && have=$(stat -c%s "$TMPD/part.$i")
    [ "$have" = "$want" ] && return 0
    # -C - 在已有部分上续传（配合 -r 时 curl 会调整 range 起点）
    if [ "$have" -gt 0 ]; then
      curl -s --noproxy '*' --max-time 900 -r $((s+have))-$e -o - "$CDN" >> "$TMPD/part.$i"
    else
      curl -s --noproxy '*' --max-time 900 -r $s-$e -o "$TMPD/part.$i" "$CDN"
    fi
    have=$(stat -c%s "$TMPD/part.$i" 2>/dev/null || echo 0)
    [ "$have" = "$want" ] && return 0
    sleep 2
  done
  echo "part $i FAILED (have=$have want=$want)"
  return 1
}

pids=()
for i in $(seq 0 $((N-1))); do dl_part $i & pids+=($!); done
fail=0
for p in "${pids[@]}"; do wait $p || fail=1; done
[ $fail -eq 1 ] && { echo "PARTS_FAILED tmpdir=$TMPD"; exit 1; }

cat $(for i in $(seq 0 $((N-1))); do echo "$TMPD/part.$i"; done) > "$OUT"
sz=$(stat -c%s "$OUT")
echo "downloaded=$sz expected=$TOTAL"
if [ "$sz" = "$TOTAL" ]; then echo "DOWNLOAD_OK"; rm -rf "$TMPD"; else echo "SIZE_MISMATCH"; exit 1; fi
