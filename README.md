# catnest（猫窝）· 自维护人机研发工作流

面向**想法与约束持续涌入、无预设评判标准、跨多会话/多仓库长程演化**项目的轻量研发工作流。纯本地 Markdown + Git + Python 3 标准库（零数据库、零向量库、零常驻服务、模型与 IDE 无关），仓库自身即用自己维护自己的 **Project #0**。

## 为什么做 `catnest`？

真实复杂工程里，想法和纠偏是一段段冒出来的：直接让 AI 写主线代码最快烂成补丁泥潭；先冻结成静态 Spec + Ticket 又会在持续变化中雪崩失效；而 95% 的上下文其实死于翻阅原始源码与长日志的 I/O 噪音。

| 常见方案的死角 | `catnest` 的做法 |
|---|---|
| **Spec + Ticket**：假设需求先想清楚再拆票，持续纠偏下票据迅速腐烂 | **流式碰撞 + 代码二分**：想法先进 `recall`/`open/` 碰撞；拿不准写隔离 **探针代码** 测出负经验河岸后扔掉，解法显然后再浇 **河床代码** |
| **纯 RAG / 静态 `AGENTS.md`**：没有失效机制，过期文档顶着权威语气误导模型；禁令越叠越厚 | **九命缓存 + 物化撤出**：`[意图]` 坦白无机器检验，`[事实]` 绑可执行猫须探针并用 `check --mutate` 抓假穿透；能物化成结构/探针的规则立刻撤出日常上下文 |
| **多 Agent 角色割据**：每个角色抱私有笔记，跨模块交界处信息全丢在传话里 | **共享猫窝，猫即组装配方**：所有猫共享同一份 `canon + open + logs`，`boot.md` 只存路由配方，`assemble <猫名>` 串起哪串原子当下就是哪只猫 |
| **待办池堆积 vs 删历史**：半成品想法不删变垃圾场，删了丢负经验 | **ACT-R 水下小岛**：零向量中文二元组 BM25 + 别名加权 + ACT-R 激活度；久未碰的 `purr` 沉入 `logs/` 不删除，新想法撞上时自动捞回 |
| **靠 AI 自报问题或自动自改**：模型只会替自己合理化，无人监管自改又陷死循环 | **被动留痕 × 人工授权复盘**：`purr --transcript` 只抽不泄密的结构指针（重复读、报错断连、纠偏词 step），供显式 `retro` 复盘拍板 |

## 一、完整运作闭环

```text
  [持续想法/修正] ──► recall (BM25+别名+ACT-R) ──► 撞出旧意图/负经验/沉水日志
                                                        │
        ┌─────────────────── 未验证 / 还在打架 ◄────────┴────────► 已围出显然解法 ──┐
        ▼                                                                           ▼
     open/*.md（活跃张力）                                                   河床代码（主线）
        │  撞出“不能同时为真” → 派一次性触手 / 隔离探针代码（用完必扔）      不变量入深层 / 摇摆锁薄层
        ├──► 过关：结论写回 canon/（跨域双向回写）并删去对应 open/                  │
        └──► 久未碰：purr --apply 移入 logs/underwater-YYYY-MM.md（不删）          ▼
                                                                    check (按 diff 跑 probes/)
                                                                        ├──► 失败/过期 → _state/suspect.md
                                                                        └──► assemble <猫名> 开机自动挂载
```

## 二、30 秒上手与接入

```sh
git clone https://github.com/sch246/catnest.git && cd catnest
python3 ./catnest.py status          # 查看猫窝本体状态
python3 ./catnest.py check --mutate  # 跑 4 条自检猫须探针 + 变异防假穿透测试
python3 ./catnest.py assemble orange # 按“橘猫”配方组装全局前台最小上下文

# 可选：软链安装为 Agent 全局 Skill（Claude Code / Codex / Antigravity 等通用）
ln -sfn "$(pwd)/skills/catnest" ~/.agents/skills/catnest

# 接入任意新项目（单仓可放 .catnest/，跨多仓放独立目录并在 boot.md 写明仓库映射）
python3 ./catnest.py init /path/to/my-nest --name my-proj
# 将 templates/AGENTS-snippet.md 贴入目标项目 AGENTS.md；可选挂载提交反射：
python3 ./catnest.py --root /path/to/my-nest check --install-hook /path/to/code-repo
```

## 三、目录契约与精确语法

- **`boot.md`**：潜意识路由表（环境红线 + `## 猫配方` + 下一拍接力棒，≤100 行，严禁复述 `canon` 正文）。
- **`canon/*.md`**：现行真相（仅存代码无法自明的意图、取舍与负经验河岸），严格二分 `[意图]` 与 `[事实]`：
  ```markdown
  ### [ID] 标题
  - **性质**：`[意图]` 或 `[事实]`
  - **断言**：一句话说清不变量或明确不要什么（已物化细节撤回一句 Why）。
  - **锚点**：`[意图]` 仅填 `logs/<文件>.md#R1`（坦白无机器检验，禁挂 probes/）；
              `[事实]` 必填 `probes/probe_*.py` 或带路径作用域的 `field:<目标>@<YYYY-MM-DD>(glob1,glob2)`。
  - **死亡条件**：什么现实变化或 `Supersedes` 会让本条失效。
  - **别名**：口语同义词1, 同义词2
  ```
- **`open/*.md`**：活跃悬案与跨域张力（frontmatter 含 `id`, `title`, `status: active`, `last_touched: YYYY-MM-DD`, `collisions: [...]`）；解决后回写 `canon/` 并删除，超期未碰由 `purr --apply` 移入 `logs/underwater-YYYY-MM.md`。
- **`probes/probe_*.py`**：猫须探针（模板见 [templates/probe-template.py](templates/probe-template.py)），顶部注释声明 `# watches:`、`# atoms:`、可选 `# mutate: relpath::old=>new` 与 `# summary:`；返回非 `0` 即写入 `_state/suspect.md`。
- **`logs/*.md`**（只追加溯源/摩擦/沉水底库）与 **`_state/`**（机器派生视图，`.gitignore` 忽略，严禁手写）。

## 四、CLI 命令速查（详见 `python3 ./catnest.py <cmd> --help`）

| 命令 | 作用与关键参数 |
|---|---|
| `init [dir] [--name N]` | 初始化新猫窝目录与默认 `boot.md` |
| `status` | 查看原子、探针、悬案、日志数量与 `suspect.md` 状态 |
| `assemble [猫名] [--list\|--print\|--json]` | 按 `boot.md` 配方输出最小文件集（自动计入所含原子采纳）；有 `## FAIL`/`## EXPIRED` 时挂载 `suspect.md` |
| `recall "<查询>" [--top 6] [--no-logs]` | 中文二元组 BM25 + 别名 3× + ACT-R 召回（检索本身不刷活跃度，后续 15 分钟内 `touch`/`assemble` 才计真实采纳） |
| `touch <ID或open/名>` | 显式标记采纳并刷新 ACT-R 活跃度（同时更新 `open/` 的 `last_touched`） |
| `check [--all\|--mutate\|--diff REF] [--repo PATH] [--install-hook REPO]` | 机器反射刷新 `_state/suspect.md`；`--mutate` 执行变异检验防假穿透；`--install-hook` 安装非阻塞 `post-commit` |
| `friction "<现象>" [--kind miss\|false-alarm\|bloat\|drift\|other] [--atom ID] [--open] [--meta]` | 记录主动摩擦；`--open` 升格进 `open/`；`--meta` 跨项目直写回 `$CATNEST_HOME` |
| `purr` / `settle [--days 14] [--repo PATH] [--transcript JSONL] [--apply]` | 沉水超期 `open/`，汇总换词连查/未采纳、Git 回退与会话指针（写 `_state/trace_signals.md`，不抄原文）供显式 `retro` 复盘 |

## License

[MIT](LICENSE)
