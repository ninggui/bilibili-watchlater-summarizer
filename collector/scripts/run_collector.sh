#!/bin/bash
# B站稍后再看自动收集 — 定时/手动外壳（只输出一行结果）
# 必需: BILI_COOKIE（完整 cookie 串）或 BILI_COOKIE_FILE（凭证文件路径）
# 可选: BILI_DATA_DIR（积压池/ledger/暂停开关所在目录）、BILI_SKIP_UPS（黑名单 JSON）、BILI_DRY_RUN=1
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${BILI_LOG_DIR:-$HERE/../logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/collector_$(date +%Y%m%d).log"
python3 "$HERE/bilibili_watch_later.py" > "$LOG_FILE" 2>&1
RESULT=$?
if [ $RESULT -eq 0 ]; then
    python3 - "$LOG_FILE" <<'PY'
import json, sys
line = None
for l in open(sys.argv[1], encoding="utf-8"):
    l = l.strip()
    if l.startswith("{") and '"added"' in l:
        line = l
if not line:
    print("✅ B站稍后再看任务完成（结果解析失败，详见日志）")
    raise SystemExit
r = json.loads(line)
bl = f"｜黑名单跳过 {r['skipped_blacklist']}" if r.get("skipped_blacklist") else ""
if r.get("paused"):
    print(f"⏸️ 添加已暂停（只入积压池）｜本轮新入池 {r['new_videos_24h']} 条{bl}｜积压 {r['backlog']} 条｜库存 {r['toview_count']}/{r['toview_cap']}（空位 {r['free_slots']}）")
else:
    print(f"✅ 新增 {r['added']} 条｜去重跳过 {r['already_in_toview']}{bl}｜库存 {r['toview_count']}/{r['toview_cap']}")
PY
else
    echo "❌ B站稍后再看任务执行失败，详情见 $LOG_FILE"
fi
