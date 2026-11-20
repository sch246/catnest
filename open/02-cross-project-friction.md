---
id: O2
title: 接入多个外部项目时，运行摩擦如何轻量回流到 Project #0
status: active
last_touched: 2026-11-20
collisions: [T4, D4]
---

# 悬案 O2：多项目运行摩擦如何回流到工作流本体

## 现状与张力
- 当 `catnest` 同时用于多个独立仓库时，每次跑出的工作流自身摩擦（例如某条 `probes/` 写法别扭、`recall` 漏召回中文简称）发生在业务目录，而工作流本体住在 `$CATNEST_HOME`。
- **张力**：全靠人肉切目录汇报容易忘；建中心守护进程又违背 `[D4]` 零服务器边界。

## 待证伪方向（触手）
- 当前 `catnest friction --meta` 已支持从任意业务目录直接把“工作流自身摩擦”追加写入 `$CATNEST_HOME/logs/friction-YYYY-MM.md`。
- 实际接入外部项目后，观察该机制是否顺手，还是需在周期 `purr` 时跨目录汇总。
