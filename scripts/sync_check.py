#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_check.py — 多会话防漂移监督脚本（开工强制跑）
职责：检测"本地规则/数据 vs GitHub 权威源"的差异，输出差异清单与建议动作。
保证同一任务多个会话对机制的所有修改最终收敛到单一真源（GitHub 发布仓）。

对比策略：
  1) git 模式（推荐）：本地目录是 git 仓库且可 fetch 时，用 `git fetch` + `git diff origin/master`
     精确对比——无 raw CDN 缓存延迟，结果最可信；
  2) raw 模式（兜底）：无 git 环境（如纯 NAS/Hermes 无 remote）时，用 raw.githubusercontent.com
     对比——注意刚 push 的文件可能有 1~5 分钟 CDN 缓存，若报漂移但本地 git 确认已推送，属缓存延迟。

只依赖标准库 + 可选 git 命令，跨平台可跑。
"""
import subprocess
import sys
import urllib.request

# ---- 配置 ----
REPO = "ninggui/bilibili-watchlater-summarizer"
BRANCH = "master"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
# 需要对齐的文件清单：(本地候选路径列表, 仓库内路径)
# 本地结构有两种：主仓根目录放 SKILL.md；发布仓放 docs/SKILL.md
WATCH_FILES = [
    (["SKILL.md", "docs/SKILL.md"], "docs/SKILL.md"),
    (["config/skip_ups.json"], "config/skip_ups.json"),
    (["CHANGELOG.md"], "CHANGELOG.md"),
    (["scripts/sync_check.py"], "scripts/sync_check.py"),
]


def fetch_raw(path: str) -> str:
    url = f"{RAW_BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def load_local(candidates: list, base: str) -> tuple:
    """按候选路径依次尝试读取，返回 (内容, 实际路径)"""
    for rel in candidates:
        path = f"{base}/{rel}"
        try:
            with open(path, encoding="utf-8") as f:
                return f.read(), path
        except FileNotFoundError:
            continue
        except Exception as e:
            return None, f"{path} ({e})"
    return None, None


def diff_report(local: str, remote: str) -> tuple:
    """简单逐行 diff，返回 (相同?, 差异行样例)"""
    if local == remote:
        return True, []
    l_lines = local.splitlines()
    r_lines = remote.splitlines()
    diffs = []
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


def git_available(base: str) -> bool:
    """检测当前目录是否是 git 仓库且远端可达（用本地 origin/<BRANCH> 引用，不强制 fetch）"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=base, capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def git_diff_mode(base: str) -> tuple:
    """git 模式：尝试 fetch 并用 origin/<BRANCH> 对比工作区文件。
    返回 (模式名, 是否可用, 差异详情列表 or None)"""
    try:
        subprocess.run(["git", "fetch", "origin", BRANCH],
                       cwd=base, capture_output=True, text=True, timeout=60)
    except Exception:
        pass  # fetch 失败则用本地已有的 origin/<BRANCH> 引用
    diffs = []
    ok = True
    for local_cands, remote_rel in WATCH_FILES:
        local, used_path = load_local(local_cands, base)
        if local is None:
            diffs.append(f"❌ 本地缺失: {local_cands[0]}")
            ok = False
            continue
        # 用 git show origin/<BRANCH>:<path> 取远端内容（git 对象，无 CDN 缓存）
        try:
            r = subprocess.run(
                ["git", "show", f"origin/{BRANCH}:{remote_rel}"],
                cwd=base, capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                diffs.append(f"❌ 远端无此文件: {remote_rel}（{r.stderr.strip()[:60]}）")
                ok = False
                continue
            remote = r.stdout
        except Exception as e:
            return ("git", False, [f"git show 失败: {e}"])
        same, d = diff_report(local, remote)
        if same:
            diffs.append(f"✅ 一致: {remote_rel}（本地 {used_path}）")
        else:
            diffs.append(f"❌ 漂移: {remote_rel}（本地 {used_path}）")
            diffs.extend(d)
            ok = False
    return ("git", ok, diffs)


def raw_diff_mode(base: str) -> tuple:
    """raw 模式：HTTP 对比（兜底）。返回 (模式名, 是否可用, 差异详情列表 or None)"""
    diffs = []
    ok = True
    for local_cands, remote_rel in WATCH_FILES:
        local, used_path = load_local(local_cands, base)
        if local is None:
            diffs.append(f"❌ 本地缺失: {local_cands[0]}（已尝试: {', '.join(local_cands)}）")
            ok = False
            continue
        if isinstance(used_path, str) and "(" in used_path:
            diffs.append(f"❌ 本地读取失败: {used_path}")
            ok = False
            continue
        try:
            remote = fetch_raw(remote_rel)
        except Exception as e:
            diffs.append(f"⚠️  无法访问远端 {remote_rel}: {e}")
            diffs.append(f"   建议：手动核对 https://github.com/{REPO}/blob/{BRANCH}/{remote_rel}")
            ok = False
            continue
        same, d = diff_report(local, remote)
        if same:
            diffs.append(f"✅ 一致: {remote_rel}（本地 {used_path}）")
        else:
            diffs.append(f"❌ 漂移: {remote_rel}（本地 {used_path}）")
            diffs.extend(d)
            ok = False
    return ("raw", ok, diffs)


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    print("=" * 60)
    print("sync_check.py · 多会话防漂移监督")
    print(f"权威源: https://github.com/{REPO}/blob/{BRANCH}")
    print("=" * 60)
    if git_available(base):
        mode, ok, diffs = git_diff_mode(base)
        print(f"[对比模式] git（基于 origin/{BRANCH}，精确无缓存延迟）")
        if mode == "git" and not ok and any("git show 失败" in d for d in diffs):
            # git 模式核心失败 → 降级 raw
            print("  git show 失败，降级 raw 模式……")
            mode, ok, diffs = raw_diff_mode(base)
            print(f"[对比模式] raw（注意：刚 push 可能有 1~5 分钟 CDN 缓存）")
    else:
        mode, ok, diffs = raw_diff_mode(base)
        print(f"[对比模式] raw HTTP（注意：刚 push 可能有 1~5 分钟 CDN 缓存）")
    for d in diffs:
        print(d)
    print("-" * 60)
    if not ok:
        print("⚠️ 发现差异：请先对齐（改完 push / 或 pull 对齐）再开始任务！")
        print("   修正动作：git pull 对齐 -> 或本地改完 git push 广播 -> 重跑本脚本确认全绿")
        print("   提示：raw 模式若误报但 git 确认已推送，是 CDN 缓存延迟，等 1~5 分钟重跑即可")
        return 1
    print("✅ 全部一致：本地与 GitHub 权威源对齐，可以开始任务。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
