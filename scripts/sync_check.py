#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_check.py — 多会话防漂移监督脚本（开工强制跑）
职责：检测"本地规则/数据 vs GitHub 权威源"的差异，输出差异清单与建议动作。
保证同一任务多个会话对机制的所有修改最终收敛到单一真源（GitHub 发布仓）。
只依赖标准库，跨平台可跑（Hermes / NAS / 豆包云电脑均可）。
"""
import json
import sys
import urllib.request

# ---- 配置 ----
REPO = "ninggui/bilibili-watchlater-summarizer"
BRANCH = "master"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
# 需要对齐的文件清单：本地路径 -> 仓库内路径（docs/ 下为发布版 SKILL.md）
WATCH_FILES = [
    ("SKILL.md", "docs/SKILL.md"),
    ("config/skip_ups.json", "config/skip_ups.json"),
    ("CHANGELOG.md", "CHANGELOG.md"),
    ("scripts/sync_check.py", "scripts/sync_check.py"),
]


def fetch_raw(path: str) -> str:
    url = f"{RAW_BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def load_local(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def diff_report(local: str, remote: str) -> tuple:
    """简单逐行 diff，返回 (相同?, 差异行样例)"""
    if local == remote:
        return True, []
    l_lines = local.splitlines()
    r_lines = remote.splitlines()
    diffs = []
    # 取前 10 处差异行用于展示
    seen = set()
    for i, line in enumerate(l_lines):
        r = r_lines[i] if i < len(r_lines) else "<EOF>"
        if line != r and (line, r) not in seen:
            diffs.append(f"  L{i+1} 本地: {line[:80]}")
            diffs.append(f"       远端: {r[:80]}")
            seen.add((line, r))
        if len(diffs) >= 12:
            break
    if len(l_lines) != len(r_lines):
        diffs.append(f"  （行数不同：本地 {len(l_lines)} / 远端 {len(r_lines)}）")
    return False, diffs


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    print("=" * 60)
    print("sync_check.py · 多会话防漂移监督")
    print(f"权威源: {RAW_BASE}")
    print("=" * 60)
    dirty = False
    for local_rel, remote_rel in WATCH_FILES:
        local_path = f"{base}/{local_rel}"
        try:
            local = load_local(local_path)
        except FileNotFoundError:
            print(f"❌ 本地缺失: {local_rel}")
            dirty = True
            continue
        except Exception as e:
            print(f"❌ 本地读取失败: {local_rel} ({e})")
            dirty = True
            continue
        try:
            remote = fetch_raw(remote_rel)
        except Exception as e:
            print(f"⚠️  无法访问远端 {remote_rel}: {e}")
            print(f"   建议：手动核对 https://github.com/{REPO}/blob/{BRANCH}/{remote_rel}")
            dirty = True
            continue
        same, diffs = diff_report(local, remote)
        if same:
            print(f"✅ 一致: {local_rel}")
        else:
            print(f"❌ 漂移: {local_rel}")
            for d in diffs:
                print(d)
            dirty = True
    print("-" * 60)
    if dirty:
        print("⚠️ 发现差异：请先对齐（改完 push / 或 pull 对齐）再开始任务！")
        print("   修正动作：git pull 对齐 -> 或本地改完 git push 广播 -> 重跑本脚本确认全绿")
        return 1
    print("✅ 全部一致：本地与 GitHub 权威源对齐，可以开始任务。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
