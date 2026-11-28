# catnest（猫窝）· 自维护人机研发工作流

面向**想法与约束持续涌入、无预设评判标准、跨多会话/多仓库长程演化**项目的可执行研发手册。纯本地 Markdown + Git + Python 3 标准库（零数据库、零向量库、零常驻服务、模型与 IDE 无关），仓库自身即用自己维护自己的 **Project #0**。

> 跨工具判断心法归属 `rising-sea`；本手册只管可执行机制、目录契约、CLI、角色派单与探针。

## 为什么做 `catnest`？

`catnest` 有两个彼此关联、但不能混成一个的问题来源。

第一，用户的想法、修正和现实约束持续涌入，而 AI 也在同一段对话里执行任务并输出结果。两股流交织，会占满沟通信道；新想法还可能和旧意图、既有约束冲突，而用户当下未必能察觉。需要把输入先单向收进一个可回查、可整理、可与旧信息碰撞的共享板，让新输入的收纳不必立刻争用当前任务的输出；再决定哪些进入当前工作、哪些仍待现实或用户裁决。

第二，复杂工程超出单一会话能承载的范围。只靠一个上下文通读源码、长日志并同时统筹实现，会被原始 I/O 噪音耗尽。多个局部上下文可以各自接触一片现实，再由共享结构和协调者整合，突破单会话的认知窗口。

直接照想法写主线代码，容易积累成补丁；把需求先冻结成静态 Spec + Ticket，又会在持续纠偏中失效。初始实测还显示，原始源码和长日志的 I/O 会占去绝大部分上下文。`catnest` 因而同时承担输入整理和多上下文协作。

当前实现通过 `note`（别名 `inbox`）把涌入的想法或约束单向落入 `logs/inbox-YYYY-MM.md`（可选 `--open` 立 `[未闭合]` 卡），并在落盘前当场用 `recall` 碰撞既有 `[河岸]`、`[未闭合]` 与外部证据，避免打断当前任务输出；`logs/`、`open/`、`canon/` 与 `assemble --task` 分别负责留痕、保留未决、沉淀结论与开机装配。召回依据词项相关度给出碰撞线索，不会自行代替人或协调者裁定逻辑冲突。

| 常见方案的死角 | `catnest` 的做法 |
|---|---|
| **Spec + Ticket**：假设需求先想清楚再拆票，持续纠偏下票据迅速腐烂 | **流式碰撞 + 代码二分**：想法先进 `recall`/`open/` 碰撞；拿不准写隔离 **探针代码** 测出负经验河岸后扔掉，解法显然后再浇 **河床代码** |
| **无锚点规则 / 免检 `[意图]` 后门**：过期条文或伪定稿顶着权威语气污染下游 | **证据态三分 + 诚实探针分层**：`canon/` 严格区分带 `证据:` 行号锚点的 `[河岸]`、带轻量 `来由:` 锚点的 `[裁决]`（不设 `碰撞:` 填表八股）与绑探针的 `[事实]`；`check` 分栏输出 `HYGIENE` vs `ANCHORED` 并用 `--mutate` 抓假穿透 |
| **压缩摘要丢失具体词法线索 + 马太回环**：老口号高频 `touch` 霸榜，负经验与原件沉底 | **原地外部证据索引 + 河岸免衰减**：`boot.md` `## 外部证据源` 原地只读扫描 `*.md` 带出 `path#Lx-y`；`[河岸]` 与外部证据源免受 ACT-R 时间衰减压制，`[未闭合]` 张力永不随时间自动沉水 |
| **散文角色纪律形同虚设 / 强降模型诱发绕道**：按工具名限流导致代理逃去无闸通道 | **单一真源 `roles.json` + Fail-Closed 猫闸**：`roles.json` 同源驱动 `templates/roles.md` 与 `hooks/catnest_gate.py`，带服务端 `nonce` 纳管 `invoke_subagent` 与 `swarm add`，硬执行 Token 水位、累计断流熔断与一次性算子退役 |

## 一、完整运作闭环

```text
  [持续想法/修正] ──► assemble --task / recall ──► 撞出 [河岸] / [未闭合] / 外部证据 (path#Lx-y)
                                                         │
        ┌─────────────────── 顾此失彼 / [UNCLOSED] ◄─────┴─────► 已围出显然解法 ──┐
        ▼                                                                         ▼
     open/*.md（活跃张力：[未闭合]/张力: 禁按时间沉水）                    河床代码（主线）
        │  缺锚点先派 tentacle 落 _state/dig/；探针代码用完必扔          锚点明确直派一次性 worker ([done]即抛)
        │  ◄── 一手证据推翻前提：worker/deputy 带 [UNCLOSED]+行号退单 ──┘
        ├──► 定案：带 `证据:` 入 [河岸] 或带 `来由:` 入 [裁决]                         │
        └──► 已解普通项超期：purr --apply 移入 logs/underwater-*                   ▼
                                                                    check (HYGIENE | ANCHORED)
                                                                        └──► _state/suspect.md
```

## 二、30 秒上手与接入

```sh
git clone https://github.com/sch246/catnest.git && cd catnest
python3 ./catnest.py status          # 查看猫窝本体状态
python3 ./catnest.py check --mutate  # 跑自检探针（HYGIENE | ANCHORED）+ 变异防假穿透测试
python3 ./catnest.py assemble orange --task "当前议题"  # 组装最小上下文并自动撞河岸 Top-5

# 软链安装全局 Skill 与 Antigravity 猫闸 Hook（消除双份拷贝漂移）
ln -sfn "$(pwd)/skills/catnest" ~/.agents/skills/catnest
ln -sfn "$(pwd)/hooks/catnest_gate.py" ~/.gemini/config/hooks/catnest_gate.py

# 接入新项目并可选挂载提交反射：
python3 ./catnest.py init /path/to/my-nest --name my-proj
python3 ./catnest.py --root /path/to/my-nest check --install-hook /path/to/code-repo
```

## 三、目录契约与精确语法

- **`boot.md`**：潜意识路由表（环境红线 + `## 猫配方` + 可选 `## 外部证据源`（仅相对路径 `*.md` glob，`recall` 原地只读扫描带出 `path#Lx-y`）+ 接力棒，≤100 行，禁复述 `canon`）。
- **`canon/*.md`**：现行真相（取消旧 `[意图]` 免检特权，遗留 `[意图]` 在 `check` 中直接报错待迁移）：
  ```markdown
  ### [ID] 标题
  - **性质**：`[河岸]`（负经验边界）| `[裁决]`（正向定案）| `[事实]`（绑机器探针）
  - **断言**：一句话说清不变量或刚性边界（已物化细节撤回一句 Why）。
  - **证据** / **来由**：`[河岸]` 必填 `证据:`（指向 `path#Lx-y` 行号或实证锚点）；`[裁决]` 必填 `来由:`（或兼容 `证据:`，引用原话 `「…」`、`logs/...` 或 `path#Lx-y`，不设 `碰撞:` 填表八股）。
  - **锚点**：`[事实]` 必填，绑 `probes/*.py` 或 `field:target@YYYY-MM-DD(globs)`。
  - **死亡条件**：哪种可观察的现实变化或代码物化会让本条失效（禁仅写 `用户 Supersedes` / `被取代时失效` 等同义反复）。
  - **物化**：可选填 `<path>`（相对仓库根或猫窝根；目标存在时 `check` 打印温和 `WARN` 提示撤出条文，不阻断 PASS）。
  - **别名**：口语同义词1, 同义词2
  ```
- **`open/*.md`**：活跃悬案与切片交接。标题或正文含 `[未闭合]`、`[UNCLOSED]` 或 `张力:` 的未决张力受永久保护，**`purr` 严禁按 14 天未碰将其列入沉水候选**。
- **写入准则**：写 canon 必带来由与可观察死法；每条持久结论只有一个权威位置，并标明适用范围；能物化成代码/探针即撤出条文。
- **`roles.json` & `hooks/catnest_gate.py`**：角色能力与配额的**唯一真源**（文档不复写具体数字，精确阈值见 [roles.json](roles.json) 与自动生成的 [templates/roles.md](templates/roles.md)）。
  - **派单与注卡**：缺一手锚点先派 `tentacle` 查窄问题落 `_state/dig/`，锚点明确则直派 `worker`；Antigravity 宿主由 `hooks/catnest_gate.py` 在 `invoke_subagent` / `swarm add` 时随服务端 `nonce` 戳记**自动注入对应角色卡**（Codex 等无 hook 宿主用 `assemble --role` 显式带入）。
  - **证伪退单**：一手源码或运行证据推翻派单前提时，`worker`/`deputy` 停止受影响切片并带 `[UNCLOSED]` 与 `file:line` 回传，由主控决定是否更新 `open/`（`canon/`、`open/` 保持主控单写）。
- **`probes/probe_*.py`**：猫须探针（模板见 [templates/probe-template.py](templates/probe-template.py)），顶部声明 `# kind: HYGIENE | ANCHORED`（未声明默认 `HYGIENE`）、`# watches:`、`# atoms:`、可选 `# mutate:` 与 `# summary:`。
- **`logs/*.md`**（只追加溯源/摩擦/沉水底库）与 **`_state/`**（机器派生视图，`.gitignore` 忽略）。

## 四、CLI 命令速查（详见 `python3 ./catnest.py <cmd> --help`）

| 命令 | 作用与关键参数 |
|---|---|
| `init [dir] [--name N]` | 初始化新猫窝目录与默认 `boot.md` |
| `status` | 查看原子、探针、悬案、日志数量与 `suspect.md` 状态 |
| `assemble [猫名] [--role main\|deputy\|worker\|tentacle] [--task "<议题>"] [--files-only\|--print\|--json]` | 按配方直出角色卡与上下文；默认最多 200 行或 25 KB，超出的整份文件列为按需读取；传入 `--task` 时自动追加 `[河岸]`/`[未闭合]`/外部证据 Top-5 碰撞结果 ([记忆分层依据](https://www.anthropic.com/research/components-of-agent-memory)) |
| `recall "<查询>" [--top 6] [--no-logs]` | 中文二元组 BM25 + 别名 3× + 原地外部证据扫描（`[河岸]` 与外部证据源免受 ACT-R 时间衰减压制） |
| `touch <ID或open/名>` | 显式标记采纳并刷新 ACT-R 活跃度（同时更新 `open/` 的 `last_touched`） |
| `check [--all\|--mutate\|--diff REF] [--repo PATH] [--install-hook REPO]` | 分栏输出 `HYGIENE: m/m \| ANCHORED: k/k` 并刷新 `_state/suspect.md`；`--mutate` 防假穿透 |
| `note` / `inbox "<想法或约束>" [--open] [--context CTX] [--top 5]` | 单向收集新想法入 `logs/inbox-YYYY-MM.md`（不挂重门禁），落盘前自动碰撞既有 `[河岸]`/`[未闭合]`/外部证据；`--open` 同步建 `[未闭合]` 保护卡 |
| `friction "<现象>" [--kind miss\|false-alarm\|bloat\|drift\|other] [--atom ID] [--open] [--meta]` | 记录运行摩擦；`--open` 升格进 `open/`；跨项目 `--meta` 暂存至 `$CATNEST_HOME/_state/meta-inbox.md` |
| `purr` / `settle [--days 14] [--repo PATH] [--transcript JSONL] [--apply]` | 沉水已闭环超期 `open/`（豁免 `[未闭合]`/`张力:`），汇总猫闸规则级客观触发/绕行分母，提取回退与会话结构指针供人工授权 `retro` |

## License

[MIT](LICENSE)
