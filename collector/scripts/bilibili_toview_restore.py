#!/usr/bin/env python3
"""
B站稍后再看 — 恢复被自动腾位移除的条目

用法:
  python3 bilibili_toview_restore.py                # 列出最近一次被移除的 50 条
  python3 bilibili_toview_restore.py --last 100     # 列出最近 100 条
  python3 bilibili_toview_restore.py --restore --last 100   # 真正恢复最近 100 条
  python3 bilibili_toview_restore.py --search 关键词  # 按标题关键词查找
  python3 bilibili_toview_restore.py --restore --search 关键词

记录文件: $BILI_DATA_DIR/bilibili_toview_ledger.json（默认 <脚本>/../data/）
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bilibili_watch_later import LEDGER, add_to_toview, get_toview_items, log  # noqa: E402


def load_ledger():
    if not os.path.exists(LEDGER):
        print(f"没有记录文件: {LEDGER}")
        return []
    with open(LEDGER, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true", help="真正执行恢复（默认只预览）")
    ap.add_argument("--last", type=int, default=50, help="取最近 N 条记录")
    ap.add_argument("--search", type=str, default="", help="按标题/UP主关键词过滤")
    args = ap.parse_args()

    entries = load_ledger()
    if args.search:
        entries = [e for e in entries
                   if args.search in (e.get("title") or "") or args.search in (e.get("owner") or "")]
    picked = entries[-args.last:]

    print(f"记录总数 {len(entries)}，本次列出 {len(picked)} 条")
    for e in picked:
        print(f"  {e.get('removed_at')} | {e.get('owner')} | {e.get('title','')[:40]} | {e.get('link')}")

    if not args.restore:
        print("\n（预览模式，加 --restore 才会真正重新添加）")
        return

    existing = {x.get("aid") for x in get_toview_items() if x.get("aid")}
    added = 0
    for e in picked:
        if e.get("aid") in existing:
            continue
        try:
            add_to_toview(e["aid"])
            added += 1
            print(f"  ✅ 已恢复 {e.get('title','')[:40]}")
            time.sleep(1.0)
        except Exception as ex:
            print(f"  ❌ 恢复失败 {e.get('title','')[:40]} — {ex}")
    print(f"\n恢复完成: {added} 条")


if __name__ == "__main__":
    main()
