# B站「稍后再看」逐条总结器

自动拉取 B站「稍后再看」列表，按视频类型智能路由（官方AI提纲→字幕→妙记兜底→纯放松跳过），用大模型生成高密度中文总结，写入带 Todo 勾选块的飞书云文档。

## 核心特性

- **智能路由，不走弯路**：先判断视频值不值得花 token——纯音乐/花艺/ASMR/带货/30秒短视频直接一句话带过；知识/观点类才读完整字幕
- **官方AI提纲优先**：调 B站官方 `x/web-interface/view/conclusion/get`（wbi签名），60% 视频直接拿官方提纲，省 90% 字幕读取量
- **字幕优先，妙记兜底**：有字幕走 `x/player/wbi/v2`；无字幕且值得转写的才下载视频→转MP3→上传飞书妙记
- **写飞书原生 Todo 块**：`<checkbox done="false">N. 标题</checkbox>`，看完打勾，后续可扩展自动从 B站删除
- **严格原序**：按 B站稍后再看原顺序写入，方便对照网页查找
- **限速保护**：B站请求间隔 2s，412 自动退避；lark-cli 写文档间隔 2-3s，避免风控

## 工作流

```
B站稍后再看列表
    ↓
元信息（标题/UP主/分区/时长）
    ↓
路由决策
    ├─ skip_music/skip_short → 一句话带过
    ├─ 官方AI提纲可用 → 直接用
    ├─ 有字幕 → wbi/v2 拉字幕
    └─ 无字幕但值得 → 下载→MP3→飞书妙记
    ↓
大模型生成高密度总结（核心论点+关键数据+论证链）
    ↓
XML 格式追加到单一飞书文档（checkbox + h2 章节）
```

## 快速开始

### 1. 安装依赖

```bash
pip install requests
# 妙记兜底需要 lark-cli（飞书 CLI），见 doubao-video-extract skill
```

### 2. 配置凭证

```bash
# B站 Cookie（浏览器 F12 → Network → 任意请求 → Cookie）
export BILI_COOKIE='SESSDATA=xxx; bili_jct=xxx; buvid3=xxx; DedeUserID=你的UID'
```

### 3. 拉数据

```bash
# 拉前10条测试
python3 scripts/bili_digest.py --limit 10 --json output/sample.json

# 拉全量
python3 scripts/bili_digest.py --json output/all_routed.json
```

### 4. 生成总结

把 `all_routed.json` 喂给任意大模型（豆包/Qwen/DeepSeek），用以下 prompt：

```
你是一个视频内容分析师。下面是 B站「稍后再看」N 条视频的字幕/元数据。
请为每条视频生成"讲透"密度的中文总结：
- 核心论点（一句话）
- 关键数据/事实（3-5个）
- 论证链/故事线
- 金句或反常识观点
纯放松类（音乐/花艺/ASMR/带货/短视频）一句话带过即可。
输出 XML 格式，每条：
<checkbox done="false">N. 视频标题</checkbox>
<p>总结正文，关键短语用<b>加粗</b></p>
```

### 5. 写入飞书

```bash
# 用 lark-cli 追加到已有文档
lark-cli docs +update --doc <DOC_TOKEN> --command append \
  --content "@./summaries.xml" --doc-format xml --as user
```

## 模型成本估算

| 项目 | 数值 |
|------|------|
| 每条平均输入 | ~2700 token（含字幕） |
| 每条平均输出 | ~500 token |
| 717条总输入 | ~193万 token |
| 717条总输出 | ~36万 token |
| Qwen3.8-Flash 成本 | 约 0.7-1.0 元 |

官方AI提纲帮约60%视频省了90%字幕读取量，实际消耗更低。

## 目录结构

```
.
├── scripts/
│   ├── bili_digest.py        # 主取数+路由脚本
│   └── transcribe_fallback.py # 妙记兜底
├── config/
│   └── config.example.yaml   # 配置模板
├── output/                   # 输出目录（gitignore）
└── README.md
```

## 已识别的纯放松类 UP 主（可永久跳过）

- 野生花艺师Fiona
- 中国国家地理景观
- 草莓蛋糕呢-

## 已读同步机制（待实现）

1. 用户在飞书文档打勾 Todo
2. 定时脚本 fetch 飞书文档，检测 `done="true"` 的 checkbox
3. 解析标题中的序号 N，调用 B站 API 从「稍后再看」删除对应视频
4. 同时删除飞书文档中该段内容

## License

MIT
