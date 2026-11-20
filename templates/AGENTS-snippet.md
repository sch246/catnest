# catnest（猫窝）L1 引导片段（贴入项目的 AGENTS.md，替换 <CATNEST_HOME> 与 <猫窝根>）

1. **开机按猫配方装原子**：新会话先跑 `python3 <CATNEST_HOME>/catnest.py --root <猫窝根> assemble <猫名>`，只读输出的最小文件集与挂载的 `suspect.md`，严禁开局通读全仓源码。
2. **想法涌入先碰撞**：遇到修正或新想法先跑 `catnest.py recall "<想法>"` 撞旧意图、`open/` 与沉水 `logs/`（真正采用时再 `touch <ID>` 或 `assemble`）；拿不准的在隔离 worktree 写**探针代码**跑实测后扔掉，解法显然后再浇河床代码。
3. **重 I/O 必隔离**：翻大量源码、构建跑测、抓图派一次性触手叼回带行号引用的负经验河岸与“意外栏”。
4. **交付反射与显式复盘**：改完代码跑 `catnest.py check`；环境复盘跑 `catnest.py purr --transcript <jsonl>` 提取结构指针后做显式 `retro` 复盘，未经用户授权不自动改规则。
