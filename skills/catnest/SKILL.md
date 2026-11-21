---
name: catnest
description: 猫窝（catnest）自维护人机研发工作流。面向想法与纠偏持续涌入、多窗口/多仓库并行的大中型项目：所有猫共享一个窝（canon + open + logs），猫是有名字的上下文组装配方而非割据实体；猫须探针（probes）做机器反射，BM25 + ACT-R 水下小岛做语义反射，代码分必扔的探针代码与按置信度浇筑的河床代码。当用户提到猫窝、catnest、猫猫小队、boot.md、猫须探针、呼噜代谢或需要维护持续演化的项目真相与工作流时使用。
---

# 猫窝工作流（catnest）

唯一权威规范与精确语法见本技能所属仓库根目录的 `README.md`（相对本文件 `../../README.md`）；本文件仅做触发入口与命令路由，不重复抄写 `canon` 条款。

设 `<CATNEST_HOME>` 为 `catnest` 仓库目录（即 `$(cd "$(dirname <SKILL.md>)/../.." && pwd)`）。

## 日常核心动作

```sh
# 1. 开机按猫配方直出最小上下文与角色契约卡（默认 --role main 直出正文，零 read_file 启动）
python3 <CATNEST_HOME>/catnest.py --root <窝> assemble <猫名>
# 派副手或窄触手时可提取对应 6 行角色卡贴入子代理 brief：
python3 <CATNEST_HOME>/catnest.py --root <窝> assemble --role deputy
python3 <CATNEST_HOME>/catnest.py --root <窝> assemble --role tentacle

# 2. 新想法/修正进来先碰撞旧意图、open/ 与沉水 logs/（检索不自动算采纳，真正 touch/assemble 才计采纳）
python3 <CATNEST_HOME>/catnest.py --root <窝> recall "<想法或关键词>"
python3 <CATNEST_HOME>/catnest.py --root <窝> touch <原子ID或open/名>

# 3. 交付后跑猫须反射（--mutate 做探针变异检验，专杀永远 PASS 的假穿透）
python3 <CATNEST_HOME>/catnest.py --root <窝> check --all
python3 <CATNEST_HOME>/catnest.py --root <窝> check --mutate

# 4. 呼噜代谢与客观复盘信号提取（不抄私密原文，输出 step 指针供显式 retro 取证）
python3 <CATNEST_HOME>/catnest.py --root <窝> purr --repo <仓> --transcript <transcript.jsonl> [--apply]
python3 <CATNEST_HOME>/catnest.py --root <窝> friction "<现象>" --kind miss|false-alarm|bloat|drift --meta
```

## 两条硬纪律

1. **三档分流与分批短写（详见 `assemble` 注入的 `templates/roles.md`）**：已知路径且 `≤3` 文本文件主控自读自改；`1~2` 问未知/重负载直派窄触手（1 触手 1 问，主控硬禁直读图片/二进制/原始 dump）；`≥3` 问或跨仓调查派 `1` 副手递归扇出并分节短写（`≤100` 行/次，草稿入 `_state/dig/`、实证入 `logs/`）；主控派完无事立即结束回合等唤醒。探针代码用完必扔，河岸围出显然解法再浇河床代码。
2. **自演进走人工授权复盘（`retro`）**：优化工作流或仓库环境时，结合 `purr --transcript` 产出的 `_state/trace_signals.md` 指针回原会话取证——优先物化成结构并撤出条文，单次失误绝不写成永久规则，严禁自动自改循环。
