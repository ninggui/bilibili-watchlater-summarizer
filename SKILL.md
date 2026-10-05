---
name: bilibili-watchlater-summarizer
description: B站「稍后再看」全链路——收集端自动归集关注 UP 主新视频（Feed 轮询/去重/积压池/黑名单），总结端按分区与字幕质量零成本分流后逐条生成中文总结并写入带 Todo 勾选块的飞书文档。触发：整理稍后再看、B站视频总结、稍后再看摘要、补跑总结。
---

# B站稍后再看 · 自动收集 + 逐条总结（统一入口）

本仓是「B站稍后再看」全链路的**统一入口**，包含两端，各自有一份详细协议：

| 端 | 职责 | 详细协议 |
|---|---|---|
| **收集端** | 关注 UP 主动态 → 去重 → 积压池 → 有空位时按发布时间补进「稍后再看」 | [`collector/SKILL.md`](./collector/SKILL.md) |
| **总结端** | 按原序拉取稍后再看 → 零成本分流 → 字幕/转写 → 大模型总结 → 写飞书文档 | [`docs/SKILL.md`](./docs/SKILL.md) |

两端的**唯一约定是「稍后再看」这个列表本身**：收集端只负责往里放，总结端只负责按原序读。

## 什么时候用

- 用户说"整理一下稍后再看""B站视频总结""稍后再看摘要"
- 定时任务跑完收集后，需要按新增条目生成/追加总结文档
- 出现"待转写""未匹配 BV"等滞留条目，需要按队列闭环消化

## 全链路（一图）

```
关注的 UP 主动态 ──▶ B站「稍后再看」(上限 1000) ──▶ 总结端
   Feed API 轮询          收集端只负责放             路由 → 大模型
   去重/积压池/黑名单                        ──▶ 飞书云文档（Todo 勾选块）
```

## 入口命令

**收集端**（默认暂停添加，只入积压池）：

```bash
python3 collector/scripts/bilibili_watch_later.py     # 单次收集
bash    collector/scripts/run_collector.sh           # 带一行结果输出（适合定时任务）
```

**总结端**（4 步，详见 `docs/SKILL.md`）：

```bash
# 第 1 步 取数 + 分流（秒级，不花模型 token）
python3 scripts/bili_digest.py --limit 10 --json output/summaries/digest.json

# 第 2 步 仅对高价值无字幕视频转写（无飞书环境跳过，改本地 Whisper）
python3 scripts/transcribe_fallback.py --digest output/summaries/digest.json

# 第 3 步 把 digest JSON 交给 AI，加载 prompts/summary_prompt_final.md 生成总结
# 第 4 步 写入飞书
lark-cli docs +create --doc-format markdown \
  --title "B站稍后再看视频摘要（日期）" \
  --content "@./output/summaries/final.md" --as user
```

## 目录

```
bilibili-watchlater-summarizer/
├── SKILL.md                      # 本文件：统一入口（两端导航）
├── collector/                    # 收集端
│   ├── SKILL.md                  #   收集协议（v5 规则 / 黑名单 / 已知坑）
│   └── scripts/                  #   bilibili_watch_later.py + 去重 + 恢复 + run_collector.sh
├── docs/SKILL.md                 # 总结端协议（路由 / 校验 / 排版规范 / 多会话公约）
├── scripts/                      # 总结端：bili_digest.py / transcribe_fallback.py / audit.py / sync_check.py
├── config/
│   ├── config.example.yaml
│   └── skip_ups.json             # UP 黑名单（收集端与总结端共用同一份）
├── assets/  output/  requirements.txt
└── 会话交接说明.md
```

## 凭证（不硬编码，不提交）

| 环境变量 | 作用 |
|---|---|
| `BILI_COOKIE` | 完整 cookie 串（优先） |
| `BILI_COOKIE_FILE` | 凭证文件路径（自动取含 `SESSDATA=` 的行） |
| `BILI_DATA_DIR` | 积压池 / ledger / 暂停开关所在目录 |
| `BILI_SKIP_UPS` | UP 黑名单 JSON 路径（默认 `<仓>/config/skip_ups.json`） |
| `BILI_DRY_RUN=1` | 演练：跑全流程但不 add/del、不写状态 |

Cookie 通过环境变量传入，**切勿写进代码或提交 GitHub**。

## 三条最容易被忽略的约束

1. **稍后再看上限 1000 条**：满仓时 add 返回 `塞满啦！先看看库存吧~`，不是登录问题；库存由用户自己看片腾出，积压池保证不丢视频。
2. **默认暂停添加**：暂停文件常驻时每轮只入积压池；恢复 = 删除该文件，之后按发布时间从早到晚补加（单轮上限 60 条）。
3. **UP 黑名单三端生效**：收集端入库前过滤 → 总结端拉取分流 → 文档总结输出，名单见 `config/skip_ups.json`。

## 跨平台复用

- `scripts/bili_digest.py` 只依赖 `requests`，无模型/飞书依赖，任意环境可跑；
- 换模型只影响总结端的第 3 步；换输出（Notion/Obsidian/邮件）只改第 4 步；
- 无飞书环境把第 2 步的妙记转写换成本地 Whisper，结果填进同样的 `minutes.summary` 字段，后续流程不变。
