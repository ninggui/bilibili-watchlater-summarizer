<div align="center">


![cover](assets/cover.png)

# B站稍后再看 逐条总结器

**自动拉取 B站「稍后再看」，按视频类型智能路由，用大模型生成高密度中文总结，写入带 Todo 勾选块的飞书云文档。**

把 717 条、127 小时的"稍后再看"，压缩成一份可对照原序、可勾选已读、可自动清理的知识摘要。

<p>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white" alt="Python 3.10+" /></a>
  <a href="#"><img src="https://img.shields.io/badge/bilibili-wbi-00A1D6?logo=bilibili&logoColor=white" alt="Bilibili WBI" /></a>
  <a href="#"><img src="https://img.shields.io/badge/feishu-doc-3370FF?logo=lark&logoColor=white" alt="Feishu Doc" /></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" /></a>
</p>

[为什么做](#为什么做) · [30秒上手](#30秒上手) · [工作流](#工作流) · [智能路由](#智能路由不走弯路) · [效果示例](#效果示例) · [成本估算](#成本估算) · [NAS部署](#部署到nas)

</div>

---

## 为什么做

B站看视频确实花时间。717 条稍后再看 ≈ 127 小时，全部看完需要一个月。但其中：

- 约 10% 是纯音乐 / 花艺 / ASMR / 带货 / 30秒短视频——**看了也白看**
- 约 60% B站已经有官方 AI 提纲——**不用重复读字幕**
- 剩余 30% 才是真正需要花 token 读字幕、让大模型讲透的知识/观点内容

本工具把这三层自动分开，**不花冤枉钱**。

## 30秒上手

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

然后把 `sample.json` 喂给任意大模型（豆包 / Qwen / DeepSeek），用 README 里的 prompt 模板生成 XML，再用 `lark-cli` 追加到飞书文档。

<details>
<summary><strong>没有 lark-cli？看最小可用路径</strong></summary>

1. `bili_digest.py` 只负责取数，不依赖飞书
2. 输出 JSON 含 title / up / subtitle / official_ai_outline / route
3. 你可以直接把 JSON 丢给任何大模型生成 Markdown
4. 飞书写入是可选增强——有 lark-cli 才能写 Todo 块

</details>

## 工作流

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

## 智能路由（不走弯路）

| 路由 | 触发条件 | 处理方式 | 单条成本 |
|------|---------|---------|---------|
| `skip_music` | 纯音乐/花艺/ASMR/已知放松UP主 | 一句话带过 | ~50 token |
| `skip_short` | 短于 60 秒 | 一句话带过 | ~50 token |
| `official_ai` | B站官方 AI 提纲可用（60% 覆盖） | 直接用官方提纲 | ~200 token |
| `subtitle` | 有字幕 | wbi/v2 拉完整字幕 | ~2700 token |
| `transcribe` | 无字幕但知识区长视频 | 下载→MP3→飞书妙记 | 妙记免费，仅加工耗 token |

**已识别的纯放松类 UP 主**（可永久跳过）：野生花艺师Fiona、中国国家地理景观、草莓蛋糕呢-。

## 效果示例

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

## 成本估算

| 项目 | 数值 |
|------|------|
| 单条平均输入（含字幕） | ~2,700 token |
| 单条平均输出 | ~500 token |
| 717 条总输入 | ~193 万 token |
| 717 条总输出 | ~36 万 token |
| **Qwen3.8-Flash 总成本** | **约 0.7–1.0 元** |

官方 AI 提纲帮 60% 视频省了 90% 字幕读取量，实际消耗比外推更低。

## 为什么不是直接用 B站 AI 总结

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

# 3. 配 crontab，每周一凌晨拉新增
0 3 * * 1 cd /path/to/repo && python3 scripts/bili_digest.py --new --json output/new.json >> /var/log/bili_digest.log 2>&1
```

配合 Qwen3.8-Flash API，全量 717 条跑完不到 1 块钱。

## 目录结构

```
.
├── scripts/
│   ├── bili_digest.py         # 主取数+wbi签名+路由
│   └── transcribe_fallback.py # 妙记兜底
├── config/
│   └── config.example.yaml   # 配置模板
├── output/                    # 输出目录（gitignore）
├── requirements.txt
└── README.md
```

## 已读同步（Roadmap）

- [x] 飞书原生 Todo 勾选块
- [ ] 定时检测 `done="true"` 的 checkbox
- [ ] 调用 B站 API 从「稍后再看」删除对应视频
- [ ] 同时删除飞书文档中该段内容

## License

MIT
