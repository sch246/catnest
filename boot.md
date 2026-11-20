# catnest（猫窝）· 潜意识路由表（boot.md）

> 猫是有名字的上下文组装配方，不是割据实体；所有猫共享同一个窝（`canon/` + `open/` + `logs/`）。本文件只做路由，严禁复述 `canon/` 正文或堆历史流水账。

## 环境与仓库映射
- **猫窝根（Project #0 自举）**：`.`（`self=.`）
- **运行入口**：`python3 ./catnest.py <cmd>`（零外部依赖，Python 3 标准库）
- **不可破坏边界**：未经用户明确授权，不自动改动外部业务仓 `.git/hooks` 或全局配置。

## 猫配方（`catnest assemble <猫名>`）
- `orange`（橘猫 · 全局前台与取舍裁决）：`canon/01-tensions.md`, `open/*.md`
- `builder`（工匠猫 · 实现与河床施工）：`canon/03-realization.md`, `probes/probe_cli_contract.py`
- `meta`（自演进猫 · 修改数据流机制或做 `retro` 复盘）：`canon/*.md`, `open/*.md`, `probes/*.py`

## 下一拍接力棒
- **下一拍**：在真实会话中跑 `catnest purr --transcript <jsonl>` 积累客观痕迹，结合 `retro` 复盘纪律检验哪些摩擦值得继续物化。
- **待决张力**：见 `open/`（宿主内过程折叠桥接；多项目摩擦回流实测）。
