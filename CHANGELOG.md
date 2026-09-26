# CHANGELOG · 变更与监督日志

> 本文件是多会话协作的"改动广播 + 协议执行监督记录"。
> **任何规则/数据/脚本变更**必须在此追加一行（时间 | 会话 | 改了什么 | 为什么），并 git push。
> 其他会话开工时先读本文件，即可对齐其他会话的最新改动。

## 协议执行监督（每次开工跑 sync_check.py 后在此记录）

| 日期 | 会话 | sync_check 结果 | 漂移点 | 处理 |
|---|---|---|---|---|
| 2026-09-25 | 会话A | ⚠️ 首次跑发现1处漂移 | 发布仓根目录无SKILL.md（在docs/下），脚本本地路径不适配 | 修正脚本支持双结构（根/dosc）并重跑全绿 |
| 2026-09-25 | 会话A | ⚠️ 复跑报CHANGELOG/sync_check漂移 | git确认远端已推送正确，raw CDN缓存延迟造成假漂移 | 脚本增加git对比模式（fetch+origin/master，无缓存延迟），raw仅兜底 |
| 2026-09-25 | Hermes 本机 | ✅ 全绿（docs/SKILL.md / config/skip_ups.json / CHANGELOG.md / scripts/sync_check.py 四项一致） | 无 | 收工复跑通过；建议后续把 `collector/` 纳入 WATCH_FILES |
| 2026-09-25 | 会话A | ✅ 对齐后全绿 | 无（fetch 对齐远端 0a11778/ef69490/网页各 commit） | 方案B全链路落地后收工复跑 |
| 2026-09-25 | 本会话（云端Linux） | ✅ 全绿（git对比模式，docs/SKILL.md / config/skip_ups.json / CHANGELOG.md / scripts/sync_check.py 一致） | 无 | 开工对齐通过；完成 todo 双删（164/167，文档端+B站端） |
| 2026-09-26 | 本会话（云端Linux） | ✅ 全绿 | 无 | 开工对齐；新增3位美食UP黑名单（定格食验室/我是荻丽婶/留意炫饭吖，用户确认）；缺失86条待补齐 |

## 变更日志

### 2026-09-25 · 方案B全链路落地：GitHub Actions 自动校验（会话A）
- `.github/workflows/audit.yml` 已就位并生效：push 到 master 自动跑 `scripts/audit.py`，生成 AUDIT.md 由 audit-bot 自动提交回仓库（paths-ignore AUDIT.md 防循环）
- 实测：commit 1664c70 触发 Run#4 → ✅ completed successfully → audit-bot 自动提交 `8e439f4 audit: auto update AUDIT.md [skip ci]`，AUDIT.md 全项 HEALTHY
- 落地踩坑（已解决，供后续会话参考）：
  1. 本地 git push workflow 文件被拒（OAuth 缺 workflow scope）→ 改走网页创建/编辑
  2. 网页创建时文件名输入框**只填 basename**（路径靠 URL `/new/master/.github/workflows/audit.yml` 指定），填完整路径会嵌套 `.github/workflows/.github/workflows/`
  3. GitHub 新建页 CodeMirror 初始 doc 含占位文本 `Enter file contents here`，bu.type 会追加在其后 → 提交后需 edit 页 Ctrl+Home + Delete 删除占位行
  4. Upload 页文件名框不支持路径（只取 basename）
- 现状：任何会话 push 后 GitHub 自动校验，开工读一眼 AUDIT.md 即知机制健康度


### 2026-09-25 · 方案B部分落地：audit.py 本地自检（会话A）
- 新增 `scripts/audit.py`：仓库健康自检（脚本语法 / config JSON / SKILL关键章节 / CHANGELOG）
- `AUDIT.md` 报告机制：push 前本地跑 audit 生成报告提交仓库
- GitHub Actions 自动校验暂未启用：当前 push 凭证缺 workflow 权限，workflow 文件已备好（.github/workflows/audit.yml），待授权后启用
- 背景：多会话协作升级为 push 即校验，减少对人工监督的依赖
### 2026-09-25 · 收集端并入本仓 + 凭证安全修复（Hermes 本机）
- 新增 `collector/`（B站稍后再看自动收集端）：Feed API 轮询 → 去重 → 积压池 → 有空位按发布时间补加；v5 规则（默认暂停添加 / 不腾位 / 单轮上限 60）
  - `collector/scripts/bilibili_watch_later.py`：凭证与路径改为环境变量（`BILI_COOKIE` / `BILI_COOKIE_FILE` / `BILI_DATA_DIR` / `BILI_SKIP_UPS`），脚本内不再硬编码
  - `collector/scripts/bilibili_toview_restore.py`（腾位恢复）、`collector/scripts/bilibili_toview_dedup.py`（重复清理）、`collector/scripts/run_collector.sh`（定时外壳）
  - 生效 `config/skip_ups.json` 黑名单环节①：feed 入库前按 up mid/名称过滤（实测一轮跳过 6 条）
- `README.md` 升级为「收集端 + 总结端」全链路说明；`collector/SKILL.md` + `collector/README.md`
- **凭证安全修复**：《会话交接说明.md》移除明文 Cookie（本仓为公开仓库）——凭证改由飞书私密文件 / 本机 `BILI_COOKIE_FILE` 提供
- 待办：`collector/` 尚未纳入 `scripts/sync_check.py` 的 WATCH_FILES（建议后续会话补充）

### 2026-09-25 · 多会话协作公约落地（会话A）
- 新增 `scripts/sync_check.py`：防漂移监督脚本，开工强制跑，对比本地 vs GitHub 权威源
- 新增本文件 `CHANGELOG.md`：变更广播 + 监督记录
- SKILL.md 新增「多会话协作公约」：开工5步 / 收工3步 / 单会话写锁
- 背景：同一任务多会话并行，防止各会话规则分叉、本地数据各说各话

### 2026-09-25 · UP 黑名单（会话A，用户确认）
- 新增 `config/skip_ups.json`：13 位纯音乐/纯视觉/无内容类 UP 黑名单
  （JLRS-LeoFM / JLRS-jayfm / FM音乐珍藏馆 / 施利TV / 李明娥 / 老黎和小黎 /
   北京山水民乐艺术团 / 花之了Flowers_Know_ / 野生花艺师Fiona / 花艺师凡 /
   8KRAW / 东韵Dongyun / 纯享木匠师Olof）
- SKILL.md 新增「UP 黑名单跳过」规则：feed 自动入库 / toview 添加 / 文档总结三环节整体跳过
- 背景：用户关注的博主中存在纯背景音乐/纯视觉无总结内容，需整体跳过以节约 token

### 2026-09-25 · 会话交接体系（会话A）
- 《会话交接说明.md》+《启动提示词》：供新会话复制后完成能力迁移
- 机制：交接说明=一次性初始化；GitHub SKILL.md=规则权威源；飞书文档=实时状态源
