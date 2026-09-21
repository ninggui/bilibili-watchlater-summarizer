#!/usr/bin/env python3
"""
妙记转写兜底编排（豆包/飞书环境增强模块）

读取 bili_digest.py 输出的 JSON，对 route=transcribe 的视频：
  下载→转MP3→上传飞书妙记→轮询→取回【结构化摘要】→回填 JSON
优先使用妙记 summary（几百字、已结构化），避免把逐字稿再喂给 AI，省 token。

依赖（仅豆包/飞书环境）：
  - doubao-video-extract skill（自动发现，或用环境变量 VIDEO_EXTRACT_SKILL 指定目录）
  - lark-cli 已登录授权
跨平台/无飞书环境时，本模块不可用，请把 transcribe 视频改用本地 Whisper 等转写。

用法：
  python3 transcribe_fallback.py --digest output/summaries/top10.json
  python3 transcribe_fallback.py --digest top10.json --limit 2     # 只转前2条
  python3 transcribe_fallback.py --digest top10.json --poll 20 --interval 30
"""
import os, re, sys, json, time, shutil, argparse, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_video_extract_skill():
    env = os.environ.get("VIDEO_EXTRACT_SKILL")
    candidates = []
    if env:
        candidates.append(Path(env))
    # 常见 skill 安装位置
    for base in [
        Path.home() / ".doubao/agent_mode/workspace/.skills",
        Path.home() / ".doubao/agent_mode/workspace/.user_skills",
        Path("/home/user/.doubao/agent_mode/workspace/.skills"),
    ]:
        if base.exists():
            candidates += [base / "doubao-video-extract"]
    for c in candidates:
        if (c / "scripts/minutes/social_video_to_minutes.py").exists():
            return c.resolve()
    return None


def run_json(cmd, cwd, timeout=1200):
    """运行命令并解析 stdout 的顶层 JSON（脚本会往 stderr 打进度，stdout 末尾是结果）"""
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    out = p.stdout.strip()
    try:
        return json.loads(out[out.find("{"):])
    except Exception:
        # 兜底：扫描所有可解析的顶层对象，挑含 lark_result / minute_token 的
        dec = json.JSONDecoder()
        best = None
        for m in __import__("re").finditer(r"\{", out):
            try:
                o, _ = dec.raw_decode(out[m.start():])
                if isinstance(o, dict) and ("lark_result" in o or "minute_token" in o or "success" in o):
                    best = o
            except Exception:
                continue
        if best:
            return best
        raise RuntimeError(f"无JSON输出: rc={p.returncode} stderr={p.stderr[-300:]}")


def poll_notes(minute_token, output_dir, tries, interval):
    """轮询 lark-cli vc +notes，返回 note dict（有 summary 或 transcript_file 即返回）"""
    for i in range(tries):
        p = subprocess.run(
            ["lark-cli", "vc", "+notes", "--minute-tokens", minute_token,
             "--output-dir", str(output_dir), "--format", "json"],
            capture_output=True, text=True, timeout=120,
        )
        try:
            d = json.loads(p.stdout.strip())
            note = d["data"]["notes"][0]
            art = note.get("artifacts", {}) or {}
            if art.get("summary") or art.get("transcript_file") or art.get("transcript"):
                return note
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(interval)
    return None


def _transcript_word_count(path):
    """读逐字稿，去掉时间戳行/Keywords 标记后统计有效字数；无人声时接近 0"""
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="ignore")
        lines = []
        for ln in txt.splitlines():
            ln = re.sub(r"^\d{4}-\d{2}-\d{2}.*?\|.*$", "", ln)  # 去时间戳行
            ln = ln.replace("Keywords:", "").strip()
            lines.append(ln)
        return len(re.sub(r"\s", "", "".join(lines)))
    except Exception:
        return None


def transcribe_one(skill_dir, url, work_dir, poll_tries, poll_interval):
    r = run_json(
        ["python3", "scripts/minutes/social_video_to_minutes.py", url, "--run-lark"],
        cwd=skill_dir, timeout=1800,
    )
    # 顶层结构为 {success,..., lark_result:{...}}；兼容直接返回内部结构
    lr = r.get("lark_result") if isinstance(r.get("lark_result"), dict) else r
    token = lr.get("minute_token")
    if not token:
        return {"status": "failed", "error": lr.get("last_notes_error") or "未拿到 minute_token"}
    note = None
    if lr.get("ready_state") == "ready":
        note = (lr.get("vc_notes", {}).get("data", {}).get("notes") or [None])[0]
    if not note or not ((note.get("artifacts", {}) or {}).get("summary")):
        polled = poll_notes(token, work_dir / "minutes", poll_tries, poll_interval)
        if polled:
            note = polled
    art = (note or {}).get("artifacts", {}) or {}
    kw = art.get("keywords")
    if isinstance(kw, dict):
        kw = kw.get("keywords")
    transcript_file = art.get("transcript_file") or lr.get("transcript_file")

    # 有摘要：成功
    if art.get("summary"):
        return {"status": "success", "minute_token": token, "minute_url": lr.get("minute_url"),
                "summary": art.get("summary"), "keywords": kw,
                "transcript_file": transcript_file, "doubao_doc_file": lr.get("doubao_doc_file")}

    # 无摘要：读逐字稿判断是"还在转写"还是"本来就无人声"
    wc = _transcript_word_count(transcript_file) if transcript_file else None
    if wc is not None and wc < 30:
        return {"status": "no_speech", "minute_token": token, "minute_url": lr.get("minute_url"),
                "transcript_words": wc, "note": "妙记转写几乎无有效语音，判定无人声，应回退卡片/跳过"}
    if wc and wc >= 30:
        return {"status": "transcript_only", "minute_token": token, "minute_url": lr.get("minute_url"),
                "transcript_file": transcript_file, "transcript_words": wc,
                "note": "逐字稿已生成但摘要未就绪，可稍后重跑或直接用逐字稿"}
    return {"status": lr.get("status", "processing"), "minute_token": token,
            "minute_url": lr.get("minute_url"), "note": "妙记仍在处理，可稍后重跑（断点续转不会重复已完成项）"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", required=True, help="bili_digest.py 输出的 JSON")
    ap.add_argument("--limit", type=int, default=0, help="最多转写几条（0=全部）")
    ap.add_argument("--poll", type=int, default=20, help="妙记轮询次数")
    ap.add_argument("--interval", type=int, default=30, help="轮询间隔秒")
    ap.add_argument("--force", action="store_true", help="强制重转（含已成功的）")
    args = ap.parse_args()

    skill_dir = find_video_extract_skill()
    if not skill_dir:
        print("❌ 未找到 doubao-video-extract skill，请用环境变量 VIDEO_EXTRACT_SKILL 指定其目录")
        sys.exit(2)
    print(f"✅ 发现 video-extract skill: {skill_dir}")

    digest_path = Path(args.digest)
    data = json.loads(digest_path.read_text(encoding="utf-8"))
    work_dir = digest_path.parent

    todo = [x for x in data if x.get("route") == "transcribe"]
    if not args.force:
        # 已拿到摘要、或已判定无人声(no_speech)的不再重复转写
        todo = [x for x in todo
                if not (x.get("minutes") or {}).get("summary")
                and (x.get("minutes") or {}).get("status") != "no_speech"]
    if args.limit:
        todo = todo[:args.limit]

    if not todo:
        print("没有需要转写的视频（可能已全部完成）")
        return
    print(f"待转写 {len(todo)} 条：{[x['bvid'] for x in todo]}\n")

    n_summary = n_nospeech = n_pending = 0
    for i, x in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {x['title'][:40]} ({x['duration']//60}:{x['duration']%60:02d})")
        try:
            m = transcribe_one(skill_dir, x["url"], work_dir, args.poll, args.interval)
            x["minutes"] = m
            if m.get("summary"):
                n_summary += 1
                print(f"    ✅ 摘要 {len(m['summary'])} 字  {m.get('minute_url','')}")
            elif m.get("status") == "no_speech":
                # 自我纠错：转写后才发现无人声，回退为元数据卡片，不再占转写名额
                n_nospeech += 1
                x["route"] = "card_meta"
                x["route_reason"] = "妙记转写判定无有效人声，回退元数据卡片"
                print("    ↩️ 无有效人声，已回退为元数据卡片（不再当口播视频总结）")
            else:
                n_pending += 1
                print(f"    ⏳ {m.get('status')}：{m.get('note','')} 可稍后重跑（自动断点续转）")
        except Exception as e:
            x["minutes"] = {"status": "error", "error": str(e)[:300]}
            n_pending += 1
            print(f"    ❌ {str(e)[:200]}")
        # 每条完成立即落盘，支持断点续转
        digest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：{n_summary} 条取得摘要，{n_nospeech} 条无人声回退卡片，{n_pending} 条待重试；已回填 {digest_path}")


if __name__ == "__main__":
    main()
