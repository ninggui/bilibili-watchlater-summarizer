<div align="center">

![cover](assets/cover.png)

# B站稍后再看 · 自动收集 + 逐条总结

**一条流水线管到底：关注的 UP 主新视频自动进「稍后再看」，稍后再看按视频类型智能路由，用大模型生成高密度中文总结，写入带 Todo 勾选块的飞书云文档。**

把 717 条、127 小时的"稍后再看"，先自动归集、再压缩成一份可对照原序、可勾选已读、可自动清理的知识摘要。

<p>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white" alt="Python 3.10+" /></a>
  <a href="#"><img src="https://img.shields.io/badge/bilibili-wbi-00A1D6?logo=bilibili&logoColor=white" alt="Bilibili WBI" /></a>
  <a href="#"><img src="https://img.shields.io/badge/feishu-doc-3370FF?logo=lark&logoColor=white" alt="Feishu Doc" /></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" /></a>
</p>

[为什么做](#为什么做) · [全链路](#全链路) · [收集端](#收集端自动归集) · [总结端](#总结端逐条总结) · [30秒上手](#30秒上手) · [智能路由](#智能路由不走弯路) · [成本估算](#成本估算) · [部署](#部署到-nas)

</div>

---

## 为什么做

B站看视频确实花时间。717 条稍后再看 ≈ 127 小时，全部看完需要一个月。但其中：

- 约 10% 是纯音乐 / 花艺 / ASMR / 带货 / 30秒短视频——**看了也白看**
- 约 60% B站已经有官方 AI 提纲——**不用重复读字幕**
- 剩余 30% 才是真正需要花 token 读字幕、让大模型讲透的知识/观点内容

本工具把这两件事都自动化：**收集端**负责"不错过、不重复、不乱序"地归集；**总结端**负责把三层内容自动分开，**不花冤枉钱**。

## 全链路

```
┌──────────────────┐     ┌────────────────────┐     ┌──────────────────┐
│  关注的 UP 主动态  │ ──▶ │  B站「稍后再看」     │ ──▶ │  总结端（本仓）    │
│  Feed API 轮询     │     │  上限 1000 条        │     │  路由 → 大模型     │
└──────────────────┘     └────────────────────┘     └────────┬─────────┘
        ▲ 收集端（本仓 collector/）                            ▼
        │  去重 / 积压池 / UP 黑名单 / 暂停开关          ┌──────────────────┐
        └────────────────────────────────────────────  │ 飞书云文档（Todo） │
                                                       └──────────────────┘
```

- **收集端**（`collector/`）：关注动态 → 去重 → 积压池 → 有空位时按发布时间补进「稍后再看」；黑名单 UP 整体跳过
- **总结端**（`scripts/` + `docs/SKILL.md`）：按原序拉取稍后再看 → 零成本分流 → 字幕/妙记 → 大模型总结 → 写飞书文档
- 两端的唯一约定是 **B站「稍后再看」这个列表本身**：收集端只负责往里放，总结端只负责按原序读

## 收集端：自动归集

`collector/scripts/bilibili_watch_later.py` —— 用关注动态 Feed API 拉取新视频，去重后进积压池，只在「稍后再看」有空位时按发布时间从早到晚补加。

| 规则 | 说明 |
|------|------|
| 默认暂停添加 | 存在暂停文件（`BILI_DATA_DIR/bilibili_add_pause`）时，本轮只把新视频收进积压池，**不 add**；恢复 = 删除该文件 |
| 不主动腾位 | 不为加新视频而删除已收藏的条目（`PRUNE_ENABLED=False`） |
| 有空位才补 | `free = 1000 - 库存`；满仓静默等待，不重试 add、不告警 |
| 补加顺序 | 按视频发布时间从早到晚（最早的积压优先），单轮上限 `MAX_ADD_PER_RUN=60` |
| UP 黑名单 | `config/skip_ups.json`：纯音乐/纯视觉/无内容类 UP 不入池、不添加、不总结 |
| 演练模式 | `BILI_DRY_RUN=1` 跑全流程但不 add/del、不写状态 |

**快速使用**

```bash
# 1. 凭证（二选一）
export BILI_COOKIE='SESSDATA=xxx; bili_jct=xxx; buvid3=xxx; DedeUserID=你的UID'
# 或：export BILI_COOKIE_FILE=/path/to/cookie.txt   # 文件里含 SESSDATA= 的那一行即可

# 2. 数据目录与黑名单（按你的环境调整）
export BILI_DATA_DIR=/path/to/data
export BILI_SKIP_UPS=$PWD/config/skip_ups.json

# 3. 跑一轮（先演练）
BILI_DRY_RUN=1 python3 collector/scripts/bilibili_watch_later.py
python3 collector/scripts/bilibili_watch_later.py          # 正式：只读列表 + 按规则补加
bash collector/scripts/run_collector.sh                    # 带一行结果输出（适合定时任务）
```

**相关工具**

```bash
# 恢复历史被腾位移除的条目（预览 / 真正恢复）
python3 collector/scripts/bilibili_toview_restore.py --last 100
python3 collector/scripts/bilibili_toview_restore.py --restore --search 关键词

# 清理重复添加的视频（只保留一条）
python3 collector/scripts/bilibili_toview_dedup.py
```

**硬约束：稍后再看上限 1000 条**

- 满仓时 add 返回 `塞满啦！先看看库存吧~`（`code != 0`），**不是登录/cookie 问题**
- 满仓不重试（旧版每天白打约 100 次 add 请求，触发风控）；积压池保证"今天没空位"的视频不会丢
- 库存由用户自己看片腾出；被腾位移除的记录写入 ledger，可一键恢复

## 总结端：逐条总结

### 30秒上手

```bash
# 1. 克隆
git clone https://github.com/ninggui/bilibili-watchlater-summarizer.git
cd bilibili-watchlater-summarizer
pip install -r requirements.txt

# 2. 填凭证
export BILI_COOKIE='SESSDATA=xxx; bili_jct=xxx; buvid3=xxx; DedeUserID=你的UID'

# 3. 拉前10条测试
python3 scripts/bili_digest.py --limit 10 --json output/sample.json
```

然后把 `sample.json` 喂给任意大模型（豆包 / Qwen / DeepSeek），用仓库内的 prompt 模板生成 XML，再用 `lark-cli` 追加到飞书文档。

<details>
<summary><strong>没有 lark-cli？看最小可用路径</strong></summary>

1. `bili_digest.py` 只负责取数，不依赖飞书
2. 输出 JSON 含 title / up / subtitle / official_ai_outline / route
3. 你可以直接把 JSON 丢给任何大模型生成 Markdown
4. 飞书写入是可选增强——有 lark-cli 才能写 Todo 块

</details>

### 工作流

```
┌─────────────────┐
│ B站稍后再看列表  │  按原序拉取，不重排
└────────┬────────┘
         ▼
┌─────────────────┐
│ 元信息+分区判断  │  时长/分区/UP主
└────────┬────────┘
         ▼
┌──────────────────────────────────┐
│           智能路由决策           │
├──────────┬──────────┬─────────────┤
│ skip_music│ official │ subtitle    │
│ skip_short│ ai提纲   │ wbi/v2字幕  │
└──────────┴──────────┴─────────────┘
         ▼
┌─────────────────┐
│ 大模型生成总结   │  核心论点+数据+论证链
└────────┬────────┘
         ▼
┌─────────────────┐
│ 飞书 XML 追加    │  checkbox + h2 章节
└─────────────────┘
```

### 智能路由（不走弯路）

| 路由 | 触发条件 | 处理方式 | 单条成本 |
|------|---------|---------|---------|
| `skip_music` | 纯音乐/花艺/ASMR/黑名单UP主 | 一句话带过 | ~50 token |
| `skip_short` | 短于 60 秒 | 一句话带过 | ~50 token |
| `official_ai` | B站官方 AI 提纲可用（60% 覆盖） | 直接用官方提纲 | ~200 token |
| `subtitle` | 有字幕 | wbi/v2 拉完整字幕 | ~2700 token |
| `transcribe` | 无字幕但知识区长视频 | 下载→MP3→飞书妙记 | 妙记免费，仅加工耗 token |

纯放松类 UP 主统一维护在 `config/skip_ups.json`（收集端与总结端共用同一份黑名单）。

### 效果示例

写入飞书后的每条长这样：

```
☐ 648. 2026网红重疾测评，谁是真王者？
  对比5-6款热门网红重疾险。核心结论：没有绝对王者——
  看重重疾单次高赔付选A，多次赔付选B，身故保障选C。
  关键选购：保额至少30-50万，保到70岁比终身性价比高。
```

- ☐ 是飞书原生 Todo 勾选块，看完点一下
- 严格按 B站稍后再看原序号 N. 开头，对照网页查找不迷路
- 每 100 条一个 h2 章节，飞书大纲自动生成目录
- 关键短语 `<b>` 加粗，扫读效率高

### 成本估算

| 项目 | 数值 |
|------|------|
| 单条平均输入（含字幕） | ~2,700 token |
| 单条平均输出 | ~500 token |
| 717 条总输入 | ~193 万 token |
| 717 条总输出 | ~36 万 token |
| **Qwen3.8-Flash 总成本** | **约 0.7–1.0 元** |

官方 AI 提纲帮 60% 视频省了 90% 字幕读取量，实际消耗比外推更低。

### 为什么不是直接用 B站 AI 总结

| 方案 | 覆盖率 | 密度 | 可控性 |
|------|--------|------|--------|
| B站官方 AI 总结 | ~60% | 一句话+大纲，偏薄 | 不可控 |
| 纯字幕+大模型 | 100% | 高但贵 | 贵 5-10 倍 |
| **本工具** | **100%** | **讲透论证，可调** | **自己选模型/prompt** |

本工具取中间：**官方提纲帮薄，字幕帮厚，纯放松帮省**。

## 部署到 NAS

```bash
# 1. NAS 上 clone
git clone https://github.com/ninggui/bilibili-watchlater-summarizer.git

# 2. 配置环境变量
export BILI_COOKIE='...'
export FEISHU_DOC_TOKEN='...'

# 3. 收集端：每天定时归集（示例 19:00）
0 19 * * * BILI_COOKIE_FILE=/path/to/cookie.txt bash /path/to/repo/collector/scripts/run_collector.sh

# 4. 总结端：每周一凌晨拉新增
0 3 * * 1 cd /path/to/repo && python3 scripts/bili_digest.py --new --json output/new.json >> /var/log/bili_digest.log 2>&1
```

配合 Qwen3.8-Flash API，全量 717 条跑完不到 1 块钱。

## 目录结构

```
.
├── collector/                     # 收集端：关注的UP主新视频 → 稍后再看
│   ├── README.md
│   ├── SKILL.md                   # 收集端规则（v5：暂停添加/不腾位/黑名单/积压池）
│   └── scripts/
│       ├── bilibili_watch_later.py    # 主脚本：Feed 轮询 + 去重 + 积压池 + 补加
│       ├── bilibili_toview_restore.py # 恢复历史被腾位移除的条目
│       ├── bilibili_toview_dedup.py   # 清理重复条目
│       └── run_collector.sh           # 定时外壳（一行结果输出）
├── scripts/                       # 总结端
│   ├── bili_digest.py             # 主取数+wbi签名+路由
│   ├── transcribe_fallback.py     # 妙记兜底
│   └── sync_check.py              # 多会话防漂移监督（开工必跑）
├── config/
│   ├── config.example.yaml        # 配置模板
│   └── skip_ups.json              # UP 黑名单（收集端+总结端共用）
├── docs/SKILL.md                  # 总结端完整规则（防错清单）
├── output/                        # 输出目录（gitignore）
├── CHANGELOG.md                   # 变更与监督日志（多会话协作）
├── 会话交接说明.md                 # 项目交接文档
├── requirements.txt
└── README.md
```

## 维护与协作

- 规则/脚本/数据以本仓为**唯一权威源**；改完跑 `python3 scripts/sync_check.py <仓库根>` 并追加 `CHANGELOG.md`
- 运行状态（todo 勾选、正文、分区）在飞书主文档，实时协作
- 凭证不落库：Cookie 走环境变量 / 本机凭证文件；本仓不含任何明文凭证

## 已读同步（Roadmap）

- [x] 飞书原生 Todo 勾选块
- [ ] 定时检测 `done="true"` 的 checkbox
- [ ] 调用 B站 API 从「稍后再看」删除对应视频
- [ ] 同时删除飞书文档中该段内容

## License

MIT
