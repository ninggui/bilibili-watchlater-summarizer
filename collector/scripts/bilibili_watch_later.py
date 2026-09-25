"""
B站关注UP主新视频 → 自动添加稍后再看 (v5)

凭证与路径（v5 起不再硬编码）:
- 凭证: 环境变量 BILI_COOKIE（完整 cookie 串）或 BILI_COOKIE_FILE（文件路径）
- 数据目录: 环境变量 BILI_DATA_DIR（积压池/ledger/暂停开关）
- UP 黑名单: 环境变量 BILI_SKIP_UPS（默认 <脚本>/../../config/skip_ups.json）
  —— 命中黑名单的 UP（纯音乐/纯视觉/无内容）不入稍后再看、不进积压池、不总结

v4 规则 (2026-09-19 用户明确):
- 不主动腾位: 不再为了加新视频而删除稍后再看里已有的条目 (PRUNE_ENABLED=False)
- 只在有剩余空位时添加: free = 1000 - 库存, 满仓静默等待, 不重试 add
- 添加顺序: 按视频发布时间从早到晚 (最早的积压优先补加)
- 未添加的视频进积压池 BACKLOG, 下次有空位时按时间顺序补; 暂停开关 PAUSE_FILE
- 演练: BILI_DRY_RUN=1

v3 保留:
- 容量感知/去重 (GET /x/v2/history/toview, 旧代码用了不存在的 /list 接口且从未调用)
- 满仓时不再逐条无效重试 (旧版每天白打 ~100 次 add 请求, 触发风控)
- 腾位移除记录写入 ledger, 可用 bilibili_toview_restore.py 恢复

v2 保留:
- 使用关注动态 Feed API (web-dynamic/v1/feed/all) 获取视频动态
- Cookie 用原始字符串直接放 header, 不用 Session.cookies.set() 避免 %2C 二次编解码
- feed 翻页使用 offset 参数, 每页 20 条
- 每条视频通过 view API 确认 pubdate 后再决定是否添加
- 翻页间隔 2 秒, 遇到 24 小时外视频立即停止
"""
import json
import os
import time
import requests
from datetime import datetime, timedelta

# ── 认证信息（禁止硬编码：从环境变量或凭证文件读取）──
# 优先 BILI_COOKIE（完整 cookie 串）；否则读 BILI_COOKIE_FILE 指向的文件（自动取含 SESSDATA= 的行）
def _load_cookie():
    raw = (os.environ.get("BILI_COOKIE") or "").strip()
    if not raw:
        path = (os.environ.get("BILI_COOKIE_FILE") or "").strip()
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if "SESSDATA=" in line:
                        raw = line.strip()
                        break
    if "SESSDATA=" not in raw:
        raise SystemExit(
            "❌ 缺少 B站凭证：请设置环境变量 BILI_COOKIE（完整 cookie 串）"
            " 或 BILI_COOKIE_FILE（凭证文件路径）。详见 README。")
    return raw


def _cookie_field(cookie, name):
    for part in cookie.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() == name:
                return v.strip()
    return ""


COOKIE_STR = _load_cookie()
BILI_JCT = _cookie_field(COOKIE_STR, "bili_jct")
UID = _cookie_field(COOKIE_STR, "DedeUserID")

# ── 配置 ──
LOOKBACK_HOURS = 24
TOVIEW_CAP = 1000        # 稍后再看硬上限（实测 count=1000 时 add 返回「塞满啦！先看看库存吧~」）
# v4 规则（2026-09-19 用户明确）:
#   ① 不主动腾位 —— 不再为了加新视频而删除稍后再看里已有的条目
#   ② 只在有剩余空位时添加 —— 满仓就静默等待, 不重试 add
#   ③ 添加顺序 —— 按视频发布时间从早到晚（最早的积压优先补加）
PRUNE_ENABLED = False    # 腾位开关: 永久关闭（保留 prune 函数与 ledger 以便人工恢复）
MAX_ADD_PER_RUN = 60     # 单轮最多添加条数（空位多时分批吃, 避免瞬时批量触发风控）
KEEP_NEWEST = 800        # 【已停用】仅保留给手工腾位使用
MAX_PRUNE_PER_RUN = 400  # 【已停用】
FREE_BUFFER = 100        # 【已停用】
PAGE_DELAY = 2.0         # 翻页间隔（秒）
VIDEO_DELAY = 1.0        # 每个视频添加间隔（秒）
DEL_DELAY = 0.7          # 每个视频移除间隔（秒）
MAX_PAGES = 30           # 翻页安全上限
# 数据目录：默认 <脚本>/../data；部署时可用 BILI_DATA_DIR 指向实际状态目录
DATA_DIR = os.environ.get("BILI_DATA_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
LEDGER = os.path.join(DATA_DIR, "bilibili_toview_ledger.json")
BACKLOG = os.path.join(DATA_DIR, "bilibili_pending_backlog.json")   # 未添加积压池（等空位按时间顺序补）
BACKLOG_MAX = 5000       # 积压池上限
PAUSE_FILE = os.environ.get("BILI_PAUSE_FILE") or os.path.join(DATA_DIR, "bilibili_add_pause")   # 存在 = 暂停添加
# UP 黑名单（纯音乐/纯视觉/无内容类整体跳过）：默认 <脚本>/../../config/skip_ups.json
SKIP_UPS_FILE = os.environ.get("BILI_SKIP_UPS") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "skip_ups.json"))
DRY_RUN = os.environ.get("BILI_DRY_RUN") == "1"   # 演练模式: 不真正 add/del

# ── HTTP 配置 ──
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# 关键: 直接用原始Cookie字符串放在header，不要用 Session.cookies.set()
# 后者会对 %2C 进行二次URL编解码，导致SESSDATA失效
# COOKIE_STR 已在「认证信息」段解析完成（BILI_COOKIE / BILI_COOKIE_FILE）

HEADERS = {
    "User-Agent": UA,
    "Cookie": COOKIE_STR,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

# ── API 端点 ──
FEED_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
TOVIEW_URL = "https://api.bilibili.com/x/v2/history/toview"          # GET 列表
TOVIEW_ADD_URL = "https://api.bilibili.com/x/v2/history/toview/add"  # POST 添加
TOVIEW_DEL_URL = "https://api.bilibili.com/x/v2/history/toview/del"  # POST 移除


def log(msg=""):
    print(msg, flush=True)


def load_skip_ups():
    """读取 UP 黑名单，返回 (mids, names)；文件缺失/损坏返回空集，不阻断主流程"""
    mids, names = set(), set()
    try:
        with open(SKIP_UPS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for up in data.get("skip_ups", []):
            if up.get("mid"):
                mids.add(up["mid"])
            if up.get("name"):
                names.add(up["name"])
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"  ⚠️ 黑名单读取失败（忽略）: {e}")
    return mids, names


SKIP_MIDS, SKIP_NAMES = load_skip_ups()


def is_skipped_up(info):
    """命中 UP 黑名单（mid 或名称）→ 不入稍后再看、不进积压池、不总结"""
    return bool(info.get("owner_mid") in SKIP_MIDS or info.get("owner") in SKIP_NAMES)


def extract_video(item):
    """从feed item中提取视频基本信息(bvid/aid/title)"""
    modules = item.get("modules", {})
    mod_dynamic = modules.get("module_dynamic", {})
    major = mod_dynamic.get("major", {})
    archive = major.get("archive") or major.get("ugc_season") or {}
    return {
        "bvid": archive.get("bvid", ""),
        "aid": archive.get("aid", 0),
        "title": archive.get("title", ""),
    }


def fetch_feed_page(offset=""):
    """获取一页关注动态Feed（仅视频类型）"""
    params = {"type": "video", "offset": offset}
    resp = requests.get(FEED_URL, headers=HEADERS, params=params, timeout=30)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"Feed API 返回错误 code={data.get('code')}: {data.get('message', 'unknown')}")
    return data["data"]


def get_video_info(bvid):
    """通过view API获取视频详细信息（含pubdate）"""
    resp = requests.get(VIEW_URL, headers=HEADERS, params={"bvid": bvid}, timeout=15)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"View API 错误: {data.get('message', '?')}")
    v = data["data"]
    return {
        "aid": v["aid"],
        "bvid": v["bvid"],
        "title": v["title"],
        "pubdate": datetime.fromtimestamp(v["pubdate"]),
        "owner": v.get("owner", {}).get("name", "?"),
        "owner_mid": v.get("owner", {}).get("mid", 0),
        "play": v.get("stat", {}).get("view", 0),
        "duration": v.get("duration", 0),
    }


def get_toview_items():
    """获取当前稍后再看全部条目（正确接口: GET /x/v2/history/toview）"""
    resp = requests.get(TOVIEW_URL, headers=HEADERS, timeout=20)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"稍后再看列表获取失败: {data.get('message', '?')}")
    return data.get("data", {}).get("list", []) or []


def add_to_toview(aid):
    """添加视频到稍后再看"""
    resp = requests.post(TOVIEW_ADD_URL, headers=HEADERS,
                         data={"aid": aid, "csrf": BILI_JCT}, timeout=15)
    result = resp.json()
    if result.get("code") != 0:
        raise Exception(f"{result.get('message', '未知错误')}")
    return True


def del_from_toview(aid):
    """从稍后再看移除"""
    resp = requests.post(TOVIEW_DEL_URL, headers=HEADERS,
                         data={"aid": aid, "csrf": BILI_JCT}, timeout=15)
    result = resp.json()
    if result.get("code") != 0:
        raise Exception(f"{result.get('message', '未知错误')}")
    return True


def append_ledger(entries):
    """把移除记录追加到 ledger（可恢复用）"""
    if not entries:
        return
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    old = []
    if os.path.exists(LEDGER):
        try:
            with open(LEDGER, "r", encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = []
    old.extend(entries)
    old = old[-8000:]  # 只保留最近 8000 条记录
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


def load_backlog():
    """读取积压池（历史未添加成功的视频, 等空位按时间顺序补加）"""
    if not os.path.exists(BACKLOG):
        return []
    try:
        with open(BACKLOG, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def save_backlog(items):
    """写回积压池（按发布时间升序, 超出上限丢弃最旧的）"""
    items = sorted(items, key=lambda x: x.get("pubdate") or 0)[-BACKLOG_MAX:]
    os.makedirs(os.path.dirname(BACKLOG), exist_ok=True)
    tmp = BACKLOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BACKLOG)


def prune_toview(items, need_free):
    """
    腾位: 按 add_at 最旧优先移除未观看条目, 直到
      free >= need_free 且 剩余条数 <= KEEP_NEWEST
    返回 (removed_list, remaining_count)
    """
    count = len(items)
    free = TOVIEW_CAP - count
    if free >= need_free and count <= KEEP_NEWEST:
        return [], count

    # 只动未观看(progress=0)的, 最旧的先走
    candidates = [x for x in items if not (x.get("progress") or 0)]
    candidates.sort(key=lambda x: x.get("add_at") or 0)

    target_count = min(KEEP_NEWEST, TOVIEW_CAP - need_free)
    removed = []
    log(f"🧹 腾位: 现有 {count} 条 / 上限 {TOVIEW_CAP}, 需空位 {need_free}, "
        f"目标保留 {target_count} 条")
    for x in candidates:
        if count <= target_count:
            break
        if len(removed) >= MAX_PRUNE_PER_RUN:
            log(f"  ⚠️ 已达单次移除上限 {MAX_PRUNE_PER_RUN} 条, 停止")
            break
        try:
            del_from_toview(x["aid"])
        except Exception as e:
            log(f"  ❌ 移除失败 {x.get('title','')[:30]} — {e}")
            continue
        removed.append({
            "removed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "aid": x.get("aid"),
            "bvid": x.get("bvid"),
            "title": x.get("title", ""),
            "owner": (x.get("owner") or {}).get("name", "?"),
            "add_at": x.get("add_at"),
            "link": f"https://www.bilibili.com/video/{x.get('bvid')}",
        })
        count -= 1
        if len(removed) % 50 == 0:
            log(f"    ...已移除 {len(removed)} 条")
        time.sleep(DEL_DELAY)

    append_ledger(removed)
    log(f"🧹 已移除 {len(removed)} 条最旧未观看条目（记录见 {LEDGER}）, 剩余 {count} 条")
    return removed, count


def main():
    log("=" * 60)
    log("  B站关注视频 → 稍后再看 (Feed API v3 · 容量感知)")
    log("=" * 60)
    log(f"  时间范围: 最近 {LOOKBACK_HOURS} 小时 | 容量上限: {TOVIEW_CAP}")

    cutoff = datetime.now() - timedelta(hours=LOOKBACK_HOURS)
    log(f"  截止时间: {cutoff.strftime('%Y-%m-%d %H:%M:%S')}")
    log()

    # ── 第1步: 读取稍后再看现状（去重 + 容量） ──
    try:
        toview_items = get_toview_items()
    except Exception as e:
        log(f"  ⚠️ 稍后再看列表读取失败: {e}")
        toview_items = []
    existing_aids = {x.get("aid") for x in toview_items if x.get("aid")}
    log(f"📦 稍后再看现有 {len(toview_items)} 条 / {TOVIEW_CAP}")
    log()

    # ── 第2步: 翻页获取视频动态 ──
    total_dynamics = 0
    video_dynamics = 0
    new_videos = []
    skipped_blacklist = 0
    seen_bvids = set()
    stop_paging = False
    offset = ""
    page = 0

    while not stop_paging and page < MAX_PAGES:
        page += 1
        log(f"📄 第 {page} 页 (offset='{str(offset)[:20]}...') ", )
        try:
            feed_data = fetch_feed_page(offset)
        except Exception as e:
            log(f"  ⚠️ 请求失败: {e}")
            break

        items = feed_data.get("items", [])
        has_more = feed_data.get("has_more", False)
        new_offset = feed_data.get("offset", "")
        total_dynamics += len(items)
        log(f"→ {len(items)} 条动态")

        if not items:
            log("  📭 无更多动态")
            break

        for item in items:
            video = extract_video(item)
            bvid = video["bvid"]
            if not bvid:
                continue
            if bvid in seen_bvids:
                continue
            seen_bvids.add(bvid)
            video_dynamics += 1

            try:
                info = get_video_info(bvid)
            except Exception as e:
                log(f"  ⚠️ {bvid} 获取详情失败: {e}")
                continue

            if info["pubdate"] >= cutoff:
                if is_skipped_up(info):
                    skipped_blacklist += 1
                    log(f"  ⏭️ [黑名单UP] {info['owner']} — {info['title'][:45]}（不入池）")
                    continue
                new_videos.append(info)
                ts = info["pubdate"].strftime("%H:%M")
                log(f"  🆕 [{ts}] {info['title'][:55]}  (UP: {info['owner']})")
            else:
                age_h = (datetime.now() - info["pubdate"]).total_seconds() / 3600
                log(f"  ⏹️  [{info['pubdate'].strftime('%m-%d %H:%M')}] "
                    f"{info['title'][:40]}  ({age_h:.1f}h前) → 停止翻页")
                stop_paging = True
                break

        if stop_paging or not has_more:
            if not has_more and not stop_paging:
                log("  📭 has_more=false，最后一页")
            break
        time.sleep(PAGE_DELAY)
        offset = new_offset

    # ── 第3步: 去重（已在稍后再看里的不再重复添加） ──
    already = [v for v in new_videos if v["aid"] in existing_aids]
    pending = [v for v in new_videos if v["aid"] not in existing_aids]

    log()
    log("-" * 50)
    log("📊 Feed 统计:")
    log(f"   翻页数: {page}")
    log(f"   总动态数: {total_dynamics}")
    log(f"   视频动态数: {video_dynamics}")
    log(f"   24h内新视频: {len(new_videos)} 个")
    log(f"   已在稍后再看(去重跳过): {len(already)} 个")
    log(f"   待添加: {len(pending)} 个")
    log("-" * 50)

    # ── 第4步: 合并积压池, 按发布时间从早到晚排队 ──
    backlog = load_backlog()
    backlog_aids = {x.get("aid") for x in backlog if x.get("aid")}
    queued = 0
    for v in pending:
        if v["aid"] in backlog_aids:
            continue
        if is_skipped_up(v):
            skipped_blacklist += 1
            continue
        backlog.append({
            "aid": v["aid"],
            "bvid": v["bvid"],
            "title": v["title"],
            "owner": v["owner"],
            "pubdate": int(v["pubdate"].timestamp()),
            "queued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        backlog_aids.add(v["aid"])
        queued += 1
    # 已在稍后再看里的从积压池剔除（人工看过/已添加过）；黑名单 UP 存量清理
    backlog = [x for x in backlog if x.get("aid") not in existing_aids and not is_skipped_up(x)]
    backlog.sort(key=lambda x: x.get("pubdate") or 0)

    free = TOVIEW_CAP - len(toview_items)
    log()
    log(f"🗂️ 积压池: {len(backlog)} 条待添加（本轮入池 {queued} 条, 按发布时间升序排队）")
    log(f"📦 剩余空位: {free} 条 / 上限 {TOVIEW_CAP}")

    # ── 第5步: 只在有空位时按时间顺序添加（不腾位, 满仓静默等待） ──
    added = 0
    skipped = 0
    done_aids = set()
    if os.path.exists(PAUSE_FILE):
        log("⏸️ 添加已暂停（存在 PAUSE_FILE）→ 本轮只入积压池, 不 add")
    elif not backlog:
        log("📭 没有需要添加的视频")
    elif free <= 0:
        log("⛔ 稍后再看已满且不腾位 → 本轮不添加, 视频留在积压池等空位（不重试 add）")
    else:
        quota = min(free, MAX_ADD_PER_RUN)
        log(f"➕ 本轮额度 {quota} 条（空位 {free}, 单轮上限 {MAX_ADD_PER_RUN}）")
        for nv in backlog[:quota]:
            when = datetime.fromtimestamp(nv["pubdate"]).strftime("%m-%d %H:%M") if nv.get("pubdate") else "?"
            try:
                if DRY_RUN:
                    log(f"  🧪[演练] [{when}] {nv.get('title','')[:50]}")
                else:
                    add_to_toview(nv["aid"])
                    log(f"  ✅ [{when}] [{nv.get('owner','?')}] {nv.get('title','')[:50]}")
                    time.sleep(VIDEO_DELAY)
                added += 1
                done_aids.add(nv["aid"])
            except Exception as e:
                msg = str(e)
                log(f"  ❌ [{when}] {nv.get('title','')[:50]} — {msg}")
                skipped += 1
                if "塞满" in msg:
                    log("  ⛔ 稍后再看已满, 停止后续添加（避免风控）")
                    break

    # 添加成功的从积压池移除
    if done_aids:
        backlog = [x for x in backlog if x.get("aid") not in done_aids]
    if not DRY_RUN:
        save_backlog(backlog)
    log(f"🗂️ 积压池剩余 {len(backlog)} 条")

    # ── 最终结果 ──
    try:
        final_count = len(get_toview_items())
    except Exception:
        final_count = len(toview_items) + added

    result = {
        "pages": page,
        "total_dynamics": total_dynamics,
        "video_dynamics": video_dynamics,
        "new_videos_24h": len(new_videos),
        "already_in_toview": len(already),
        "skipped_blacklist": skipped_blacklist,
        "pruned": 0,
        "added": added,
        "skipped": skipped,
        "free_slots": max(TOVIEW_CAP - final_count, 0),
        "backlog": len(backlog),
        "toview_count": final_count,
        "toview_cap": TOVIEW_CAP,
        "paused": os.path.exists(PAUSE_FILE),   # 暂停开关状态（v5: 默认暂停, 只入积压池）
        "dry_run": DRY_RUN,
    }

    log()
    log("=" * 60)
    log(f"✅ 完成: 动态 {total_dynamics} 条, 24h新视频 {len(new_videos)} 个 "
        f"(去重跳过 {len(already)}), 本轮添加 {added} 个, 失败 {skipped} 个, "
        f"积压 {len(backlog)} 条, 库存 {final_count}/{TOVIEW_CAP} (空位 {result['free_slots']})")
    log(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
