#!/usr/bin/env python3
"""B站稍后再看去重：删除重复添加的视频，只保留一条

凭证与数据目录由 bilibili_watch_later.py 统一解析：
  BILI_COOKIE / BILI_COOKIE_FILE（凭证）、BILI_DATA_DIR（数据目录）
用法: BILI_COOKIE_FILE=<凭证文件> python3 bilibili_toview_dedup.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bilibili_watch_later import COOKIE_STR, _cookie_field  # noqa: E402
from bilibili_api import Credential, user, video  # noqa: E402

credential = Credential(
    sessdata=_cookie_field(COOKIE_STR, "SESSDATA"),
    bili_jct=_cookie_field(COOKIE_STR, "bili_jct"),
    buvid3=_cookie_field(COOKIE_STR, "buvid3"),
)


async def main():
    # 1. 获取稍后再看列表
    try:
        wl = await user.get_toview_list(credential=credential)
    except Exception as e:
        print(f"❌ 获取列表失败: {e}")
        return
    wl_list = wl.get("list", wl.get("data", {}).get("list", []))
    print(f"当前稍后再看: {len(wl_list)} 个")

    # 2. 按 aid 分组找重复
    by_aid = {}
    for v in wl_list:
        aid = v.get("aid")
        title = v.get("title", "?")
        if aid not in by_aid:
            by_aid[aid] = []
        by_aid[aid].append((title, v.get("bvid", "")))

    dup_groups = {aid: items for aid, items in by_aid.items() if len(items) > 1}
    if not dup_groups:
        print("✅ 无重复视频")
        return

    print(f"发现 {len(dup_groups)} 组重复:")
    total_del = 0
    for aid, items in dup_groups.items():
        print(f"  {items[0][1]} | {items[0][0][:40]} (×{len(items)})")
        # 删除多余的（保留第一条）
        for title, bvid in items[1:]:
            try:
                v = video.Video(aid=aid, credential=credential)
                await v.delete_from_toview()
                total_del += 1
                print(f"    🗑️ 删除 {bvid} | {title[:30]}")
                await asyncio.sleep(1.0)
            except Exception as e:
                print(f"    ❌ 删除失败 {bvid}: {e}")

    print(f"\n✅ 去重完成: 删除 {total_del} 条重复")


if __name__ == "__main__":
    asyncio.run(main())
