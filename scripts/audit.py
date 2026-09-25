#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit.py — 仓库健康自检（GitHub Actions 每次 push 自动跑，生成 AUDIT.md）
检查项：
  1. 脚本语法（py_compile）
  2. config JSON 合法性（skip_ups.json 字段完整）
  3. SKILL.md 关键章节齐全（防规则被误删/覆盖）
  4. CHANGELOG.md 非空且含监督表
输出：AUDIT.md（提交回仓库，任何会话开工可读；workflow 用 paths-ignore 防止循环触发）
"""
import json
import os
import py_compile
import subprocess
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE)


def check_scripts() -> list:
    results = []
    scripts_dir = os.path.join(REPO_ROOT, "scripts")
    for f in sorted(os.listdir(scripts_dir)):
        if f.endswith(".py"):
            path = os.path.join(scripts_dir, f)
            try:
                py_compile.compile(path, doraise=True)
                results.append(f"✅ PASS 语法: scripts/{f}")
            except py_compile.PyCompileError as e:
                results.append(f"❌ FAIL 语法: scripts/{f} ({e})")
    return results


def check_config() -> list:
    results = []
    path = os.path.join(REPO_ROOT, "config", "skip_ups.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ups = data.get("skip_ups", [])
        required = {"mid", "name", "cat", "reason", "conf"}
        bad = [u for u in ups if not required.issubset(set(u.keys()))]
        results.append(f"✅ PASS config: skip_ups.json 可解析，{len(ups)} 条黑名单"
                       if not bad else
                       f"❌ FAIL config: {len(bad)} 条缺少必填字段 {required - set(ups[0].keys()) if ups else required}")
        conf_counts = {}
        for u in ups:
            conf_counts[u.get("conf", "?")] = conf_counts.get(u.get("conf", "?"), 0) + 1
        results.append(f"    明细: {conf_counts}")
    except Exception as e:
        results.append(f"❌ FAIL config: skip_ups.json 解析失败 ({e})")
    return results


def check_skill() -> list:
    results = []
    for p in ["docs/SKILL.md", "SKILL.md"]:
        path = os.path.join(REPO_ROOT, p)
        if os.path.exists(path):
            content = open(path, encoding="utf-8").read()
            need = ["多会话协作公约", "UP 黑名单跳过", "开工 5 步", "收工 3 步", "sync_check",
                    "wbi 签名", "标题-BV一致性校验", "勾选删除=整段删除", "章节标题同步"]
            missing = [k for k in need if k not in content]
            results.append(
                f"✅ PASS SKILL({p}): 关键规则齐全" if not missing
                else f"❌ FAIL SKILL({p}): 缺失关键章节 {missing}")
            break
    else:
        results.append("❌ FAIL SKILL: 未找到 docs/SKILL.md 或 SKILL.md")
    return results


def check_changelog() -> list:
    results = []
    path = os.path.join(REPO_ROOT, "CHANGELOG.md")
    try:
        content = open(path, encoding="utf-8").read()
        ok = len(content.strip()) > 200 and "协议执行监督" in content and "变更日志" in content
        results.append("✅ PASS CHANGELOG: 非空且含监督表与变更日志"
                       if ok else "❌ FAIL CHANGELOG: 内容异常或缺少关键 section")
    except Exception as e:
        results.append(f"❌ FAIL CHANGELOG: 读取失败 ({e})")
    return results


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        commit = subprocess.run(["git", "log", "-1", "--oneline"], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "unknown"
    sections = [
        check_scripts(),
        check_config(),
        check_skill(),
        check_changelog(),
    ]
    all_results = [r for s in sections for r in s]
    fails = [r for r in all_results if "FAIL" in r]
    status = "✅ HEALTHY" if not fails else f"❌ {len(fails)} ISSUES"
    lines = [
        "# AUDIT · 机制健康自检报告",
        "",
        f"> 自动生成：{now} ｜ commit: {commit}",
        "",
        f"**总体状态：{status}**",
        "",
        "## 检查明细",
        "",
    ]
    lines += [f"- {r}" for r in all_results]
    lines += ["", "---", "_本报告由 GitHub Actions 每次 push 自动生成。任何会话开工前可先读本文件了解机制健康度。_", ""]
    with open(os.path.join(REPO_ROOT, "AUDIT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(all_results))
    print(f"\n=> AUDIT.md 已生成，状态: {status}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
