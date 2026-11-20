---
id: O1
title: 会话内局部过程折叠（process-fold）如何桥接到外部 Agent 工具链
status: active
last_touched: 2026-11-20
collisions: [R3, T2]
---

# 悬案 O1：会话内局部过程折叠如何桥接到外部 Agent CLI

## 现状与张力
- 自研运行时（如 `yz_bot`）可在内部实现 `line__compact(scope="process")`，翻完一批文件后趁热把工具原子折成 `【过程留痕｜可召回】 + read_context(ctx)` 指针，同时保住前缀 KV 缓存。
- 但在 Claude Code / Codex / Antigravity 等外部宿主里，工作流脚本无法直接修改宿主内部的对话消息数组。
- **张力**：不折叠则单领域深聊窗口仍会因工具输出膨胀；全部外包给一次性子代理又会增加少量跨会话转述开销。

## 待证伪方向（触手）
- 检验组合方案：**重 I/O 一律派一次性子代理（含强模型深潜）+ 每波次聊完立刻用 `catnest assemble` 换干净窗口冷启动**，在真实使用两周内是否已经足够替代宿主内 `process-fold`。
- 若两周内仍频繁在单领域深聊中爆窗，通过 `catnest friction --kind bloat` 记录实证再决定是否需要外部摘要中转。
