# 2026-11 · 运行摩擦与负经验回流

- `2026-11-20 17:03` **[miss]** tokenize 把 EDGE_CHARS(如'过')从中文词中间删掉了，导致'过期'退化成单字漏命中 D2 | atom: `D3` | ctx: 首次实跑 recall '想法一直来老改主意怎么防文档过期' 暴露
- `2026-11-20 17:26` **[drift]** Opus盲审#1：T1-T3挂hygiene/boot_purity属假穿透，需拆成[意图]与[事实]两类原子 | atom: `D1` | ctx: Opus blind review #11
- `2026-11-20 17:26` **[false-alarm]** Opus盲审#2：recall以hits非空算命中导致D3永不触发且SANITY_QUERIES自证，需改用召回后采纳率+miss计数 | atom: `D3` | ctx: Opus blind review #11
- `2026-11-20 17:26` **[false-alarm]** Opus盲审#3：field过期扫全仓造误报风暴，open超21天报FAIL把沉水变闸门 | atom: `D2` | ctx: Opus blind review #11
- `2026-11-20 17:26` **[other]** Opus盲审#4：maintenance.py的pool[:max(sample*2,len)]写反min/max导致加权盲抽失效 | atom: `T4` | ctx: Opus blind review #11
- `2026-11-20 17:39` **[drift]** 零上下文盲读暴露缺少 README 运作总图与外部接入/语法说明，且 open/01 残留旧名 flow | atom: `D4` | ctx: Zero-context blind reader test
- `2026-11-21 11:19` **[bloat]** 原trace.py不扫子代理树与耗时/重跑命令，且boot一刀切全量单测+盲审违背rising-sea并暗箱捆绑附加步骤(185子代理/57个>10m/127次build) | atom: `T2`
- `2026-11-21 12:19` **[bloat]** 开机 `assemble` 只吐路径诱发连续 `read_file` 滑坡，主控等子代理期间直读 13 张图片与原始数据文件爆窗，单子代理吞 70+ 文件末尾长输出触发 `stream was interrupted` 死循环，且跨项目 `friction --meta` 缺 `_state/meta-inbox.md` 暂存隔离 | atom: `R3`
