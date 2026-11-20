# 2026-11 · 运行摩擦与负经验回流

- `2026-11-20 17:03` **[miss]** tokenize 把 EDGE_CHARS(如'过')从中文词中间删掉了，导致'过期'退化成单字漏命中 D2 | atom: `D3` | ctx: 首次实跑 recall '想法一直来老改主意怎么防文档过期' 暴露
- `2026-11-20 17:26` **[drift]** Opus盲审#1：T1-T3挂hygiene/boot_purity属假穿透，需拆成[意图]与[事实]两类原子 | atom: `D1` | ctx: Opus blind review #11
- `2026-11-20 17:26` **[false-alarm]** Opus盲审#2：recall以hits非空算命中导致D3永不触发且SANITY_QUERIES自证，需改用召回后采纳率+miss计数 | atom: `D3` | ctx: Opus blind review #11
- `2026-11-20 17:26` **[false-alarm]** Opus盲审#3：field过期扫全仓造误报风暴，open超21天报FAIL把沉水变闸门 | atom: `D2` | ctx: Opus blind review #11
- `2026-11-20 17:26` **[other]** Opus盲审#4：maintenance.py的pool[:max(sample*2,len)]写反min/max导致加权盲抽失效 | atom: `T4` | ctx: Opus blind review #11
- `2026-11-20 17:39` **[drift]** 零上下文盲读暴露缺少 README 运作总图与外部接入/语法说明，且 open/01 残留旧名 flow | atom: `D4` | ctx: Zero-context blind reader test
