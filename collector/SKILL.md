---
name: bilibili-watch-later-collector
description: B站关注UP主新视频自动收集到「稍后再看」——Feed API 轮询 + 去重 + 积压池 + UP 黑名单，默认暂停添加、有空位时按发布时间补加。
---

# B站稍后再看自动收集（收集端）

> 本目录是「B站稍后再看」全链路的收集端：把关注的 UP 主新视频自动归集到 B站「稍后再看」。
> 归集完成后，交给总结端（本仓 `docs/SKILL.md` + `scripts/`）逐条总结写入飞书文档。

## 触发方式

- 定时：`0 19 * * *`（每天 19:00，示例）
- 手动：`python3 collector/scripts/bilibili_watch_later.py`
- 带一行结果输出（适合定时任务）：`bash collector/scripts/run_collector.sh`

## 凭证与配置（不硬编码）

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `BILI_COOKIE` | 完整 cookie 串（优先） | — （与下一项必填其一） |
| `BILI_COOKIE_FILE` | 凭证文件路径（自动取含 `SESSDATA=` 的行） | — |
| `BILI_DATA_DIR` | 积压池 / ledger / 暂停开关所在目录 | `<脚本>/../data` |
| `BILI_SKIP_UPS` | UP 黑名单 JSON 路径 | `<仓>/config/skip_ups.json` |
| `BILI_DRY_RUN=1` | 演练：跑全流程但不 add/del、不写状态 | 关 |

## 工作流程（v5 · 默认暂停收集 + 有空位按时间顺序补）

1. 读取稍后再看现状：`GET /x/v2/history/toview` → 全部条目（含 aid/add_at/progress），用于去重与容量判断
2. 用关注动态 Feed API（`/x/polymer/web-dynamic/v1/feed/all?type=video`）拉取视频动态
3. offset 游标翻页，每页 20 条，翻页间隔 2 秒
4. 每条视频通过 view API（`/x/web-interface/view?bvid=xxx`）确认 pubdate 与 UP 主
5. 遇到 24 小时外的视频立即停止翻页
6. **UP 黑名单过滤**：命中黑名单（mid 或名称）的视频直接跳过，不入池
7. 去重：已在稍后再看里的 aid 不再重复添加
8. 未添加的视频写入积压池（`$BILI_DATA_DIR/bilibili_pending_backlog.json`，记录 aid/bvid/title/owner/pubdate）
9. 若暂停文件存在（默认）→ 全部留在积压池；解除暂停后按 pubdate 升序（最早优先）取 `min(空位, MAX_ADD_PER_RUN=60)` 条添加，添加成功的从积压池移除

## v5 规则（最高优先）

- **默认暂停添加**：暂停文件（`$BILI_DATA_DIR/bilibili_add_pause`）常驻存在 → 每轮只把新视频收进积压池，**不 add**；恢复 = 删除该文件
- **不主动腾位**：不为了加新视频而删除稍后再看里已有的条目（`PRUNE_ENABLED=False`，prune 函数与 ledger 保留仅供人工使用）
- **恢复后只在有剩余空位时添加**：`free = 1000 - 库存`；满仓静默等待，**不重试 add、不告警**
- **添加顺序**：按视频发布时间从早到晚（积压最早的优先补），不是按抓取顺序；单轮上限 `MAX_ADD_PER_RUN=60`
- **暂停期间照常跑**：定时任务仍每天跑（否则新视频永久丢失），输出文案 `⏸️ 添加已暂停｜本轮新入池 N｜黑名单跳过 N｜积压 N｜库存 N/1000（空位 N）`
- 演练模式：`BILI_DRY_RUN=1` 跑全流程但不 add/del、不写状态

## UP 黑名单（config/skip_ups.json）

- 口径：UP 最近视频全为纯音乐 / 纯视觉无口播（ASMR / 试听 / 演奏 / 花艺 / 风光 / 沉浸手作等），或签名明确纯音乐类；**有口播的教程类不列入**
- 生效环节：① 收集端 feed 入库前过滤（本目录）② 总结端拉取分流 ③ 文档总结
- 维护：改 `config/skip_ups.json`（mid + name）后同步本仓，收集端与总结端共用同一份

## 硬约束：稍后再看上限 1000 条

- 满仓时 add 返回 `塞满啦！先看看库存吧~`（`code != 0`），**不是登录/cookie 问题**
- 关注数 × 每日新视频量决定填满速度：610 关注 ≈ 每日 100+ 条 → 空仓 10 天填满
- 库存由用户自己看片腾出；积压池保证「今天没空位」的视频不会永久丢失
- 历史腾位移除 ≠ 删除内容，视频仍在 B站；ledger 记录 bvid/title/链接，可一键恢复
- 恢复：`python3 collector/scripts/bilibili_toview_restore.py [--search 关键词] [--last N] [--restore]`
- 去重清理：`python3 collector/scripts/bilibili_toview_dedup.py`（依赖 `bilibili-api-python`）

## 已知坑（血泪）

- **`/x/v2/history/toview/list` 不存在**（返回 404 HTML，json 解析报 `Expecting value: line 1 column 1`）——列表接口是 `GET /x/v2/history/toview`
- 早期版本 `get_toview_aids()` 写错接口且**从未被调用** → 等于没有去重，且满仓时每天白打 100 次 add 请求触发风控
- 满仓后症状：日志显示「发现 100+ 个新视频，成功添加 0~1 个，跳过 100+ 个」
- Cookie 用原始字符串直接放 header，不要用 `Session.cookies.set()`——会对 `%2C` 二次编解码，导致 SESSDATA 失效
- 排查入口：`$BILI_DATA_DIR/logs/` 下当日日志，看 `❌` 行的错误文案

## 依赖

- `requests`（主脚本）
- `bilibili-api-python`（仅去重脚本需要）
