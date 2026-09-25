# 收集端：B站稍后再看自动归集

把关注的 UP 主新视频自动收进 B站「稍后再看」，交给总结端逐条总结。

- 主脚本：`scripts/bilibili_watch_later.py`（Feed API 轮询 → 去重 → 积压池 → 有空位按发布时间补加）
- 定时外壳：`scripts/run_collector.sh`（一行结果输出）
- 工具：`scripts/bilibili_toview_restore.py`（恢复历史被腾位移除的条目）、`scripts/bilibili_toview_dedup.py`（清理重复）

完整规则见 [SKILL.md](SKILL.md)，全链路说明见 [仓库 README](../README.md)。

## 快速开始

```bash
# 凭证（二选一）
export BILI_COOKIE='SESSDATA=xxx; bili_jct=xxx; buvid3=xxx; DedeUserID=你的UID'
# export BILI_COOKIE_FILE=/path/to/cookie.txt

# 数据目录（积压池/ledger/暂停开关）与黑名单
export BILI_DATA_DIR=/path/to/data
export BILI_SKIP_UPS=$PWD/../config/skip_ups.json

# 先演练，再正式
BILI_DRY_RUN=1 python3 scripts/bilibili_watch_later.py
python3 scripts/bilibili_watch_later.py
```

## 设计要点

| 要点 | 说明 |
|------|------|
| 默认暂停添加 | 存在暂停文件时只入积压池不 add；恢复 = 删文件 |
| 不主动腾位 | 不为加新视频删已有条目 |
| 有空位才补 | 满仓静默等待，不重试、不告警 |
| 补加顺序 | 发布时间从早到晚，单轮上限 60 |
| UP 黑名单 | `../config/skip_ups.json`：纯音乐/纯视觉类不入池、不添加、不总结 |
| 演练模式 | `BILI_DRY_RUN=1` 全流程但不写状态 |
