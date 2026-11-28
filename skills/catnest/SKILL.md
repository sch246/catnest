---
name: catnest
description: 猫窝（catnest）自维护人机研发工作流。面向想法与纠偏持续涌入、多窗口/多仓库并行的大中型项目：所有猫共享一个窝（canon + open + logs），猫是有名字的上下文组装配方而非割据实体；猫须探针（probes）做机器反射，BM25 + ACT-R 水下小岛做语义反射，代码分必扔的探针代码与按置信度浇筑的河床代码。当用户提到猫窝、catnest、猫猫小队、boot.md、猫须探针、呼噜代谢或需要维护持续演化的项目真相与工作流时使用；当前项目含 `boot.md` 与 `canon/`，或 `.catnest/boot.md` 时也使用本手册装配对应上下文与角色。
---

# 猫窝工作流（catnest）

跨项目判断心法见 `rising-sea`；本技能只管可执行手册入口与命令路由。完整规范见仓库根目录 `../../README.md`，文档局部性与自然裂变参考 `../../docs/locality-blueprint.md`，角色配额与行动契约单一真源见 `../../roles.json`（及生成的 `../../templates/roles.md`）。

设 `<CATNEST_HOME>` 为 `catnest` 仓库目录（即 `$(cd "$(dirname <SKILL.md>)/../.." && pwd)`）。

## 日常核心动作

```sh
# 1. 开机按猫配方直出最小上下文、角色卡，并可用 --task 零仪式感自动撞 [河岸]/[未闭合]/外部证据 Top-5
python3 <CATNEST_HOME>/catnest.py --root <窝> assemble <猫名> [--task "<当前议题>"]
# 无 hook 宿主（如 Codex）派单前可显式提取同源角色卡（Antigravity 猫闸派单时自动注入）：
python3 <CATNEST_HOME>/catnest.py --root <窝> assemble --role deputy|worker|tentacle

# 2. 单向想法收集与修正碰撞（note 单向落盘不挂门禁，落盘前自动撞 [河岸]/[未闭合]/外部证据）
python3 <CATNEST_HOME>/catnest.py --root <窝> note "<新想法或修正>" [--open]
python3 <CATNEST_HOME>/catnest.py --root <窝> recall "<想法或关键词>"
python3 <CATNEST_HOME>/catnest.py --root <窝> touch <原子ID或open/名>

# 3. 交付后跑猫须反射（诚实分栏 HYGIENE vs ANCHORED；--mutate 抓假穿透；禁遗留免检 [意图]）
python3 <CATNEST_HOME>/catnest.py --root <窝> check --all
python3 <CATNEST_HOME>/catnest.py --root <窝> check --mutate

# 4. 呼噜代谢与复盘信号提取（豁免 [未闭合]/张力: 沉水，并汇总猫闸规则级触发/绕行客观分母）
python3 <CATNEST_HOME>/catnest.py --root <窝> purr --repo <仓> --transcript <transcript.jsonl> [--apply]
python3 <CATNEST_HOME>/catnest.py --root <窝> friction "<现象>" --kind miss|false-alarm|bloat|drift --meta
```

`assemble` 默认最多加载 200 行或 25 KB（先到者为准）；超出的整份文件会列在“按需读取”中，避免把细节复制进每轮上下文。需要完整材料时使用 `--print`，需要调整预算时用 `--max-lines` / `--max-bytes`。

## 四条硬纪律（精确配额以 `roles.json` 与 `hooks/catnest_gate.py` 为唯一真源）

1. **证据态三分与禁倾倒伪定稿**：当前代码说明现行行为，不自动证明设计意图。`canon/` 只接纳能改变后续判断、且有出处的 `[河岸]`、`[裁决]` 或绑探针的 `[事实]`；写入保留来由与可观察失效条件，源码可直接恢复的现状不重复抄录。能物化成代码/探针即撤出条文；未决冲突留在 `open/`，原始经历留在 `logs/`。
2. **分权派单、自动注卡与证伪退单**：按 `roles.json` 划分 `main` / `deputy` / `worker` / `tentacle` 权限与水位（精确数字见 `roles.json`，此处不复写）。派单与跨轮交接说明真问题、方向与取舍标准，列明用户要求及协议、现场、安全等不可退让边界，并给足一手参考；薄意图不等于少给上下文，源码现状不自动规定局部实现，局部方案由执行者推导。主控缺参考锚点时先派 `tentacle` 围绕明确入口窄探并落 `_state/dig/`，锚点已清则直派 `worker`，派出即停。Antigravity 派单由 `hooks/catnest_gate.py` 自动注入角色卡；`worker`/`deputy` 在目的或边界不清、或一手证据推翻前提时停止受影响切片并带 `[UNCLOSED]`、`file:line` 退回。
3. **自演进走人工授权复盘（`retro`）**：结合 `purr --transcript` 的 `_state/trace_signals.md` 结构指针回原会话取证——优先物化进单一真源结构并撤出散文条文，严禁无人监管的自动自改循环。
4. **语义显然后收束旧责任**：确认唯一状态权威、写入口与主路径后，移除已被替代的镜像、重复注册、静默回退和无依据兼容层。保留过渡桥时记录作用范围、验证方式和删除条件，避免把迁移过程变成第二套长期真相。
