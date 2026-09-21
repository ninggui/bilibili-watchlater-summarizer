#!/usr/bin/env python3
"""
B站稍后再看 · 视频摘要提取与分流器（严谨路由版）

设计目标：一次就走对解析路径，不为返工浪费 token / 转写时间。
本脚本只"取数 + 决策"，不调用任何模型 API：
  拉列表 → 元信息(分区/分P) → wbi 字幕(质量分级) → 弹幕高能点 → 路由决策 → 标准化 JSON
AI 总结由豆包完成；无字幕且"值得转写"的视频，再交飞书妙记（见 SKILL.md）。

用法：
  export BILI_COOKIE='SESSDATA=...; bili_jct=...; buvid3=...; DedeUserID=...'
  python3 bili_digest.py --limit 10 --json out.json
  python3 bili_digest.py --bvid BV1xxx --json one.json
  python3 bili_digest.py --limit 10            # 输出到 output/summaries/ 时间戳文件
"""
import os, re, json, time, argparse, hashlib, urllib.parse
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Cookie": os.environ.get("BILI_COOKIE", ""),
}

# ======================================================================
# 一、分区分类（决定"无字幕时值不值得花成本转写"，零走弯路的核心）
# tid 映射来源：bilibili-API-collect / biliup tid-ref（公开稳定常量）
# ======================================================================
# 高口播价值：无字幕也值得转写（知识/科技/汽车/美食/纪录片/装修/影视解说/健身）
ZONE_SPEECH_RICH = {
    # 知识区 36
    201, 124, 228, 207, 208, 209, 229, 122,
    # 科技区 188
    95, 230, 231, 232, 233,
    # 汽车区 223
    176, 224, 225, 240, 226, 227, 223,
    # 美食区 211
    76, 212, 213, 214, 215, 211,
    # 纪录片 177
    37, 178, 179, 180, 177,
    # 家居房产(装修)、健身、社科法律心理、影视杂谈/剪辑(解说类)
    239, 164, 182, 183, 36, 188,
    # 汽车区新增/细分：新能源车、汽车知识科普、赛车、改装、房车
    247, 258, 245, 246, 248,
    # 三农、出行探店、亲子、资讯（时政事评通常有口播）
    251, 250, 254, 202, 203, 204, 205, 206,
}
# 默认无口播 / 低转写价值：音乐、舞蹈、演奏、音MAD、MAD/MMD（无字幕不主动转写）
ZONE_SPEECH_LOW = {
    3, 130, 29, 59, 31, 193, 30, 194, 28,          # 音乐区及子分区
    129, 20, 154, 156, 198, 199, 200,              # 舞蹈区
    26, 24, 25, 27,                                # 音MAD / MAD·AMV / MMD
}
# 标题强信号：疑似无口播（纯声浪/纯音乐/助眠/无台词），命中且无字幕时不主动转写
# （妙记转写是最终裁判，需要时仍可手动触发；自动流程先不跑，避免白等几分钟）
TITLE_NOSPEECH = ["纯享", "纯音乐", "纯人声", "伴奏", "声浪", "asmr", "ASMR", "助眠",
                  "无台词", "无对白", "默片", "录音棚试听", "试听", "翻唱", "cover", "Cover",
                  "钢琴", "吉他演奏", "架子鼓", "白噪音",
                  # 纯视觉/纯氛围类：配乐+画面，无解说
                  "花艺", "插花", "花道", "风景", "风光", "治愈", "空镜", "桌面美学",
                  "城市漫步", "citywalk", "city walk", "航拍", "延时", "解压", "冥想", "慢生活"]
# 教学反例：标题命中这些词时，即使含上面的花艺/风光词，也视为有口播解说（如"花艺教程""风光摄影入门"）
TITLE_SPEECH_OVERRIDE = ["教程", "教学", "详解", "攻略", "怎么做", "如何", "怎么拍",
                          "入门", "讲解", "谈", "分享", "干货", "技巧", "入门到精通"]
# 分区 tid → 名称（仅覆盖常用，未知 tid 不影响路由，按未知保守处理）
ZONE_NAME = {
    201: "科学科普", 124: "社科·法律·心理", 228: "人文历史", 207: "财经商业",
    208: "校园学习", 209: "职业职场", 229: "设计·创意", 122: "野生技能协会", 36: "知识",
    95: "数码", 230: "软件应用", 231: "计算机技术", 232: "工业·工程·机械", 233: "极客DIY", 188: "科技",
    176: "汽车生活", 224: "汽车文化", 225: "汽车极客", 240: "摩托车", 226: "智能出行", 227: "购车攻略", 223: "汽车",
    247: "新能源车", 258: "汽车知识科普", 245: "赛车", 246: "改装玩车", 248: "房车",
    251: "三农", 250: "出行", 254: "亲子", 202: "资讯", 203: "热点", 204: "环球", 205: "社会", 206: "综合资讯",
    76: "美食制作", 212: "美食侦探", 213: "美食测评", 214: "田园美食", 215: "美食记录", 211: "美食",
    37: "人文·历史", 178: "科学·探索·自然", 179: "军事", 180: "社会·美食·旅行", 177: "纪录片",
    239: "家居房产", 164: "健身", 182: "影视杂谈", 183: "影视剪辑", 181: "影视",
    138: "搞笑", 21: "日常", 161: "手工", 162: "绘画", 160: "生活",
    130: "音乐综合", 29: "音乐现场", 59: "演奏", 31: "翻唱", 193: "MV", 30: "VOCALOID", 194: "电音", 28: "原创音乐", 3: "音乐",
    129: "舞蹈", 20: "宅舞", 154: "舞蹈综合", 26: "音MAD", 24: "MAD·AMV", 25: "MMD·3D",
    71: "综艺", 137: "明星", 5: "娱乐", 157: "美妆护肤", 158: "穿搭", 159: "时尚潮流", 155: "时尚",
    22: "鬼畜调教", 216: "鬼畜剧场", 127: "教程演示", 119: "鬼畜",
    85: "短片", 184: "预告·资讯", 217: "动物圈", 234: "运动",
}

# 极短视频阈值：无字幕时，低于该时长不值得花几分钟转写
SHORT_SECONDS = 30

# ======================================================================
# 二、wbi 签名（不签名的 player/v2 会返回串台字幕，必须用 wbi/v2）
# ======================================================================
_MIXIN = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,
          12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]
_wbi_mk = None


_MIN_DELAY = 2.0  # 每条请求之间至少2秒
_LAST_CALL = [0.0]  # 上次调用时间

def _get(url, retries=3, **kw):
    """限速+重试的GET请求，避免被B站反爬ban"""
    # 限速：距上次调用不足 _MIN_DELAY 就等够
    elapsed = time.time() - _LAST_CALL[0]
    if elapsed < _MIN_DELAY:
        time.sleep(_MIN_DELAY - elapsed)

    for i in range(retries + 1):
        try:
            _LAST_CALL[0] = time.time()
            r = requests.get(url, headers=H, timeout=15, **kw)
            d = r.json()
            # 412 = 反爬触发，加长延时后重试
            if d.get("code") == -412:
                wait = 10 * (i + 1)
                print(f"  [限速] 触发反爬，等 {wait}s 后重试...")
                time.sleep(wait)
                continue
            return d
        except Exception:
            if i == retries:
                return None
            time.sleep(2 * (i + 1))  # 指数退避


def _wbi_key():
    global _wbi_mk
    if not _wbi_mk:
        d = _get("https://api.bilibili.com/x/web-interface/nav")
        img = d["data"]["wbi_img"]["img_url"].rsplit("/", 1)[1].split(".")[0]
        sub = d["data"]["wbi_img"]["sub_url"].rsplit("/", 1)[1].split(".")[0]
        raw = img + sub
        _wbi_mk = "".join(raw[i] for i in _MIXIN)[:32]
    return _wbi_mk


def _wbi_sign(params):
    params["wts"] = int(time.time())
    params = dict(sorted(params.items()))
    q = urllib.parse.urlencode(params)
    params["w_rid"] = hashlib.md5((q + _wbi_key()).encode()).hexdigest()
    return params


# ======================================================================
# 三、取数
# ======================================================================
def fetch_list(limit):
    d = _get("https://api.bilibili.com/x/v2/history/toview")
    if not d or d.get("code") != 0:
        raise RuntimeError(f"拉取稍后再看失败: {d and d.get('message')}")
    return d["data"].get("list", [])[:limit]


def get_meta(bvid):
    d = _get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    return d.get("data") if d and d.get("code") == 0 else None


def _pick_chinese_track(subs):
    """优先选中文原文轨（ai-zh / zh，ai_type=0），避免选到机翻轨(ai_type=1)"""
    def score(s):
        lan = s.get("lan", "")
        is_zh = lan.startswith("zh") or lan == "ai-zh"
        is_orig = s.get("ai_type", 0) == 0
        return (is_zh, is_orig)
    return max(subs, key=score) if subs else None


def get_subtitle(bvid, cid, duration):
    """
    返回 (quality, text, lan, detail)
      quality: good / sparse / bad / none / music
      - good  : 时间覆盖 0.7~1.3、语速 1~8 字/秒，可直接用
      - sparse: 时间对得上但话很少（cps<1），知识区视为字幕不全→转写；其余出卡片
      - bad   : 串台/残缺（时间或语速越界），等同无字幕走路由
      - music : 字幕几乎全是 ♪，纯音乐/无口播
      - none  : 无字幕轨 / 拉取失败
    """
    p = _wbi_sign({"bvid": bvid, "cid": cid})
    d = _get("https://api.bilibili.com/x/player/wbi/v2?" + urllib.parse.urlencode(p))
    if not d:
        return "none", None, None, {"reason": "字幕接口请求失败"}, None
    subs = d.get("data", {}).get("subtitle", {}).get("subtitles", [])
    if not subs:
        return "none", None, None, {"reason": "无字幕轨（B站未生成AI字幕）", "tracks": 0}, None

    # 自我纠错：首选中文原文轨；若校验不过，再尝试其余轨，而不是直接放弃
    ordered = [_pick_chinese_track(subs)] + [s for s in subs if s is not _pick_chinese_track(subs)]
    last_detail = {}
    for sub in ordered:
        surl = sub.get("subtitle_url", "")
        if not surl:
            continue
        if surl.startswith("//"):
            surl = "https:" + surl
        try:
            body = requests.get(surl, headers=H, timeout=15).json().get("body", [])
        except Exception:
            continue
        if not body:
            continue
        tmax = max(x.get("to", 0) for x in body)
        raw = "".join(x.get("content", "") + " " for x in body).strip()
        chars = len(re.sub(r"[♪\s]", "", raw))
        music_marks = raw.count("♪")
        cps = chars / max(duration, 1)
        cover = tmax / max(duration, 1)
        last_detail = {"lan": sub.get("lan"), "lan_doc": sub.get("lan_doc"),
                       "cover": round(cover, 2), "cps": round(cps, 2), "chars": chars,
                       "music_marks": music_marks}
        # 纯音乐：♪ 密度很高 或 几乎没有实词
        if music_marks > 0 and chars < max(30, duration * 0.3):
            return "music", None, sub.get("lan_doc"), last_detail, None
        time_ok = 0.7 < cover < 1.3
        if not time_ok or cps > 8:
            continue  # 串台/残缺，换下一条轨
        # 长视频(>10min)生成稀疏时间锚点版（每30秒一个 [mm:ss]），短视频不带以省 token
        timed = None
        if duration >= 600:
            parts, last_bin = [], -1
            for seg in body:
                b = int(seg.get("from", 0) // 30)
                if b != last_bin:
                    parts.append(f"[{int(seg['from'])//60:02d}:{int(seg['from'])%60:02d}] ")
                    last_bin = b
                parts.append(seg.get("content", "") + " ")
            timed = "".join(parts).strip()
        if cps < 1.0 or chars < max(40, duration * 0.5):
            return "sparse", raw, sub.get("lan_doc"), last_detail, timed
        return "good", raw, sub.get("lan_doc", "中文"), last_detail, timed
    return "bad", None, None, last_detail or {"reason": "所有字幕轨均未通过校验"}, None


def get_danmaku(cid, danmaku_total):
    """仅弹幕 >100 时提取 30 秒窗口密度 top3，且只保留有信息量的弹幕"""
    if danmaku_total < 100:
        return None
    try:
        r = requests.get(f"https://comment.bilibili.com/{cid}.xml", headers=H, timeout=15)
        r.encoding = "utf-8"
        items = re.findall(r'<d p="([\d.]+)[^"]*">([^<]+)</d>', r.text)
        bins = {}
        for t, c in items:
            bins.setdefault(int(float(t) // 30) * 30, []).append(c)
        hot = []
        for b, cs in sorted(bins.items(), key=lambda x: -len(x[1]))[:3]:
            informative = [c for c in cs if len(c) >= 8 and not re.fullmatch(r'[哈啊嗯哦嘿呀哇~！？？\s,.，。]+', c)]
            if informative:
                hot.append({"time": f"{b//60:02d}:{b%60:02d}", "count": len(cs), "samples": informative[:5]})
        return hot or None
    except Exception:
        return None


# ======================================================================
# 四、路由决策（零走弯路核心）
# 返回 route: subtitle / transcribe / skip_music / skip_short / card_meta
# ======================================================================
def decide_route(tid, duration, sub_quality, danmaku_total, desc, title=""):
    zone = ZONE_NAME.get(tid, "未知分区")
    rich = tid in ZONE_SPEECH_RICH
    low = tid in ZONE_SPEECH_LOW
    title_nospeech = next((k for k in TITLE_NOSPEECH if k.lower() in (title or "").lower()), None)
    # 教学反例：花艺/风光标题若带"教程/详解/怎么拍"等，说明有口播解说，不按无口播处理
    if title_nospeech and any(k in (title or "") for k in TITLE_SPEECH_OVERRIDE):
        title_nospeech = None

    # 1) 优质字幕：直接用，最省
    if sub_quality == "good":
        return "subtitle", f"优质字幕（{zone}）"
    if sub_quality == "music":
        return "skip_music", "字幕全为音乐标记，无口播"

    # 2) 稀疏字幕：知识区怀疑字幕不全→转写补全；其余用稀疏字幕出卡片
    if sub_quality == "sparse":
        if rich and duration >= SHORT_SECONDS and not title_nospeech:
            return "transcribe", f"{zone}内容但字幕过疏，转写补全"
        return "card_meta", "字幕稀疏，按元数据+少量字幕出卡片"

    # 3) 无字幕 / 字幕串台(bad)：先按零成本信号判断要不要花转写成本
    # 3a) 标题强信号疑似无口播（纯享/声浪/ASMR…），不主动转写
    if title_nospeech:
        return "card_meta", f"标题含「{title_nospeech}」疑似无解说，先出元数据卡片（需要可手动转写）"
    if low:
        return "skip_music", f"{zone}类无字幕，默认无口播，不转写省成本"
    if duration < SHORT_SECONDS:
        return "skip_short", f"仅{duration}s且无字幕，转写性价比低，用元数据卡片/跳过"
    if rich:
        return "transcribe", f"{zone}高价值内容，无字幕→妙记转写（用妙记摘要，不取逐字稿）"
    # 生活区/娱乐等不确定：有一定时长或互动量才转写，否则元数据卡片
    if duration >= 60 or danmaku_total >= 50 or len(desc or "") >= 30:
        return "transcribe", f"{zone}内容，时长/互动达标→妙记转写"
    return "card_meta", f"{zone}短视频且互动少，元数据卡片即可"


def assess_depth(quality, text, duration, route):
    """有字幕可用时，按有效字数定总结深度"""
    if route != "subtitle" or not text:
        return {"density": 0, "depth": route}
    effective = len(re.sub(r"[♪\s]", "", text))
    cps = effective / max(duration, 1)
    if effective >= 800 and cps >= 2.5:
        density, depth = 5, "full"
    elif effective >= 400:
        density, depth = 4, "full"
    elif effective >= 200:
        density, depth = 3, "card_plus"
    else:
        density, depth = 2, "card_only"
    return {"density": density, "depth": depth, "cps": round(cps, 1), "effective_chars": effective}


# ======================================================================
# 五、主流程（单条隔离，任一条失败不影响其它）
# ======================================================================
def process(v, idx):
    bvid = v["bvid"]
    md = get_meta(bvid)
    if not md:
        return {"bvid": bvid, "route": "error", "reason": "元信息拉取失败"}
    cid, dur, tid = md["cid"], md["duration"], md["tid"]
    pages = [{"page": p["page"], "cid": p["cid"], "part": p.get("part", "")} for p in md.get("pages", [])]

    quality, sub, lan, sub_detail, timed = get_subtitle(bvid, cid, dur)
    route, reason = decide_route(tid, dur, quality, md["stat"]["danmaku"], md.get("desc"), md["title"])
    a = assess_depth(quality, sub, dur, route)
    # 弹幕采集已按用户要求取消（省请求、避免把弹幕当内容）；保留字段为 None 兼容
    hot = None

    return {
        "bvid": bvid, "cid": cid, "tid": tid, "zone": ZONE_NAME.get(tid, f"未知({tid})"),
        "title": md["title"], "owner": md["owner"]["name"],
        "duration": dur, "pages_count": len(pages), "pages": pages if len(pages) > 1 else None,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "desc": (md.get("desc") or "")[:300],
        "stat": {k: md["stat"][k] for k in ["view", "danmaku", "like", "coin", "favorite"]},
        "subtitle": sub, "subtitle_timed": timed, "subtitle_len": len(sub) if sub else 0,
        "subtitle_quality": quality, "subtitle_detail": sub_detail,
        "route": route, "route_reason": reason,
        "assessment": a, "danmaku_hotspots": hot,
    }


ROUTE_TAG = {
    "subtitle": "用字幕", "transcribe": "★需妙记转写", "skip_music": "跳过(无口播)",
    "skip_short": "跳过(极短)", "card_meta": "元数据卡片", "error": "错误",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--bvid", type=str)
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()

    targets = [{"bvid": args.bvid}] if args.bvid else fetch_list(args.limit)
    out = []
    for i, v in enumerate(targets, 1):
        try:
            item = process(v, i)
        except Exception as e:
            item = {"bvid": v.get("bvid"), "route": "error", "reason": f"处理异常: {e}"}
        out.append(item)
        if item.get("title"):
            star = "⭐" * item["assessment"].get("density", 0)
            print(f"{i:2}. [{item['duration']//60:2d}:{item['duration']%60:02d}] {item['zone']:8} "
                  f"{star or '  '} {item['title'][:26]:26} → {ROUTE_TAG.get(item['route'], item['route'])}")
        else:
            print(f"{i:2}. ❌ {item.get('bvid')} → {item.get('reason')}")
        # 每条视频之间额外等 3 秒，避免触发反爬
        if i < len(targets):
            time.sleep(3)

    outpath = args.json or str(ROOT / "output" / "summaries" / f"digest_{time.strftime('%Y%m%d_%H%M%S')}.json")
    Path(outpath).parent.mkdir(parents=True, exist_ok=True)
    Path(outpath).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    by_route = {}
    for x in out:
        by_route.setdefault(x["route"], []).append(x)
    print(f"\n📦 输出: {outpath}")
    for r, xs in by_route.items():
        sample = [x.get("bvid") for x in xs][:8]
        print(f"   {ROUTE_TAG.get(r, r):14} {len(xs)} 条 {sample if r in ('transcribe','error') else ''}")
    tl = by_route.get("transcribe", [])
    if tl:
        print("\n下一步：对下列视频走飞书妙记转写（在线视频先转MP3），取回后用妙记【摘要】而非逐字稿：")
        for x in tl:
            print(f"   {x['url']}   # {x['title'][:30]}")


if __name__ == "__main__":
    main()
