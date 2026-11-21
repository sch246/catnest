# catnest（猫窝）L1 引导片段（贴入项目的 AGENTS.md，替换 <CATNEST_HOME> 与 <猫窝根>）

1. **开机直出配方与角色卡**：新会话先跑 `python3 <CATNEST_HOME>/catnest.py --root <猫窝根> assemble <猫名>`（默认注入 `main` 角色卡并直出全文，无需再连发 `read_file`），严禁开局通读全仓源码。
2. **想法涌入先碰撞**：遇到修正或新想法先跑 `catnest.py recall "<想法>"` 撞旧意图、`open/` 与沉水 `logs/`（真正采用时再 `touch <ID>` 或 `assemble`）；拿不准的在隔离 worktree 写**探针代码**跑实测后扔掉，解法显然后再浇河床代码。
3. **三档分流与短写防断流**：已知路径 `≤3` 文本文件主控自读；`1~2` 问派窄触手（1 触手 1 问，主控硬禁直读图片/二进制/原始 dump）；`≥3` 问派 `1` 副手（`assemble --role deputy`）扇出并分节短写（`≤100` 行/次），派出后无事立即结束回合等唤醒。
4. **交付反射与显式复盘**：改完代码跑 `catnest.py check`；环境复盘跑 `catnest.py purr --transcript <jsonl>` 提取结构指针后做显式 `retro` 复盘，未经用户授权不自动改规则。
