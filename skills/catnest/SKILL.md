---
name: catnest
description: 猫窝（catnest）自维护人机研发工作流。面向想法与纠偏持续涌入、多窗口/多仓库并行的大中型项目：所有猫共享一个窝（canon + open + logs），猫是有名字的上下文组装配方而非割据实体；猫须探针（probes）做机器反射，BM25 + ACT-R 水下小岛做语义反射，代码分必扔的探针代码与按置信度浇筑的河床代码。当用户提到猫窝、catnest、猫猫小队、boot.md、猫须探针、呼噜代谢或需要维护持续演化的项目真相与工作流时使用。
---

# 猫窝工作流（catnest）

跨项目心法与三轴原则见 `rising-sea`；本技能只管可执行手册入口与命令路由。完整规范见仓库根目录 `../../README.md`，角色配额与行动契约单一真源见 `../../roles.json`（及生成的 `../../templates/roles.md`）。

设 `<CATNEST_HOME>` 为 `catnest` 仓库目录（即 `$(cd "$(dirname <SKILL.md>)/../.." && pwd)`）。

## 日常核心动作

```sh
# 1. 开机按猫配方直出最小上下文、角色卡，并可用 --task 零仪式感自动撞 [河岸]/[未闭合]/外部证据 Top-5
python3 <CATNEST_HOME>/catnest.py --root <窝> assemble <猫名> [--task "<当前议题>"]
# 无 hook 宿主（如 Codex）派单前可显式提取同源角色卡（Antigravity 猫闸派单时自动注入）：
python3 <CATNEST_HOME>/catnest.py --root <窝> assemble --role deputy|worker|tentacle

# 2. 新想法/修正碰撞（含 boot.md ## 外部证据源 path#Lx-y 原地扫描；[河岸] 与外部证据免衰减）
python3 <CATNEST_HOME>/catnest.py --root <窝> recall "<想法或关键词>"
python3 <CATNEST_HOME>/catnest.py --root <窝> touch <原子ID或open/名>

# 3. 交付后跑猫须反射（诚实分栏 HYGIENE vs ANCHORED；--mutate 抓假穿透；禁遗留免检 [意图]）
python3 <CATNEST_HOME>/catnest.py --root <窝> check --all
python3 <CATNEST_HOME>/catnest.py --root <窝> check --mutate

# 4. 呼噜代谢与复盘信号提取（含 [未闭合]/[UNCLOSED]/张力: 的 open 豁免按时间沉水）
python3 <CATNEST_HOME>/catnest.py --root <窝> purr --repo <仓> --transcript <transcript.jsonl> [--apply]
python3 <CATNEST_HOME>/catnest.py --root <窝> friction "<现象>" --kind miss|false-alarm|bloat|drift --meta
```

## 三条硬纪律（精确配额以 `roles.json` 与 `hooks/catnest_gate.py` 为唯一真源）

1. **证据态三分与禁倾倒伪定稿**：`canon/` 只接纳带 `证据:` 行号/实证锚点的 `[河岸]`、带 `来由:` 出处锚点的 `[裁决]` 与绑探针的 `[事实]`；写 canon 必带来由与可观察死法，能物化成代码/探针即撤出条文；未决冲突留在 `open/` 标 `[未闭合]` / `张力:`。
2. **分权派单、自动注卡与证伪退单**：按 `roles.json` 划分 `main` / `deputy` / `worker` / `tentacle` 权限与水位（精确数字见 `roles.json`，此处不复写）。主控缺一手参考锚点时先派 `tentacle` 围绕明确入口查窄问题落 `_state/dig/`，锚点已清再直派 `worker`（来源明确时不多跑侦察），派出即停；派单给薄层高层意图 + 极薄硬边界 + 充足一手参考路径与行号。Antigravity 派单由 `hooks/catnest_gate.py` 自动注入对应角色卡；一手证据推翻派单前提时，`worker`/`deputy` 停止受影响切片并带 `[UNCLOSED]` 与 `file:line` 退单，由主控决定是否更新 `open/`。
3. **自演进走人工授权复盘（`retro`）**：结合 `purr --transcript` 的 `_state/trace_signals.md` 结构指针回原会话取证——优先物化进单一真源结构并撤出散文条文，严禁无人监管的自动自改循环。
