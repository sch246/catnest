"""Self-maintenance: friction backflow and periodic settle (sink open, alias hints, blind sample)."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from . import actr_score, load_uses, parse_canon_atoms, state_dir, touch_key
from .trace import analyze_transcript, write_trace_report

LAST_TOUCHED_RE = re.compile(r"^last_touched:\s*(\d{4}-\d{2}-\d{2})", re.M)


def _engine_root() -> Path:
    return Path(os.environ.get("CATNEST_HOME") or Path(__file__).resolve().parent.parent).expanduser().resolve()


def cmd_friction(root: Path, args: argparse.Namespace) -> int:
    engine_root = _engine_root()
    root_resolved = root.resolve()
    now = datetime.now()
    atom_part = f" | atom: `{args.atom}`" if args.atom else ""
    ctx_part = f" | ctx: {args.context}" if args.context else ""

    if args.meta and root_resolved != engine_root:
        inbox = state_dir(engine_root) / "meta-inbox.md"
        if not inbox.exists():
            inbox.write_text(
                "# _state/meta-inbox.md（跨项目工作流摩擦暂存箱，禁直接入公开库；显式 `retro` 脱敏提炼后再入 `logs/`）\n\n",
                encoding="utf-8",
            )
        entry = f"- `{now.strftime('%Y-%m-%d %H:%M')}` **[{args.kind}]** (nest=`{root_resolved.name}`) {args.summary}{atom_part}{ctx_part}\n"
        with inbox.open("a", encoding="utf-8") as f:
            f.write(entry)
        print(f"staged cross-project meta friction (gitignored) -> {inbox}")
        return 0

    target = engine_root if args.meta else root_resolved
    logs_dir = target / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"friction-{now.strftime('%Y-%m')}.md"
    if not log_file.exists():
        log_file.write_text(f"# {now.strftime('%Y-%m')} · 运行摩擦与负经验回流\n\n", encoding="utf-8")

    entry = f"- `{now.strftime('%Y-%m-%d %H:%M')}` **[{args.kind}]** {args.summary}{atom_part}{ctx_part}\n"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(entry)

    opened_path: Path | None = None
    if args.open:
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", args.summary).strip("-")[:24] or "item"
        opened_path = target / "open" / f"friction-{now.strftime('%m%d')}-{slug}.md"
        opened_path.parent.mkdir(parents=True, exist_ok=True)
        opened_path.write_text(
            f"---\nid: F-{now.strftime('%m%d%H%M')}\ntitle: {args.summary}\nstatus: active\n"
            f"last_touched: {now.strftime('%Y-%m-%d')}\ncollisions: [{args.atom or ''}]\n---\n\n"
            f"# 摩擦升级：{args.summary}\n\n- 类型：`{args.kind}`\n- 来源：`{log_file.relative_to(target)}`\n"
            f"- 现场上下文：{args.context or '（待补充）'}\n",
            encoding="utf-8",
        )
        touch_key(target, f"open/{opened_path.stem}")

    print(f"logged friction -> {log_file}")
    if opened_path:
        print(f"promoted to open -> {opened_path}")
    return 0


def _open_age_days(path: Path, today: date) -> int:
    m = LAST_TOUCHED_RE.search(path.read_text("utf-8"))
    if m:
        try:
            return (today - date.fromisoformat(m.group(1))).days
        except ValueError:
            pass
    return (today - date.fromtimestamp(path.stat().st_mtime)).days


def recall_adoption_stats(root: Path, window_secs: int = 900) -> dict:
    """Measure real recall usefulness: adopted within window (touch/assemble) + logged [miss] frictions."""
    rlog = state_dir(root) / "recall.jsonl"
    uses = load_uses(root)
    recs: list[dict] = []
    if rlog.is_file():
        for ln in rlog.read_text("utf-8").splitlines()[-200:]:
            try:
                recs.append(json.loads(ln))
            except ValueError:
                continue
    adopted = 0
    unadopted_queries: list[str] = []
    retry_pairs: list[tuple[str, str]] = []
    for i, rec in enumerate(recs):
        ts = rec.get("ts", 0)
        q = rec.get("query", "")
        hits = rec.get("hits", [])
        is_adopted = any(ts <= t <= ts + window_secs for hid in hits for t in uses.get(hid, []))
        if is_adopted:
            adopted += 1
        else:
            unadopted_queries.append(q)
            if i + 1 < len(recs) and 0 <= recs[i + 1].get("ts", 0) - ts <= 180:
                nq = recs[i + 1].get("query", "")
                if nq and nq != q:
                    retry_pairs.append((q, nq))
    miss_count = 0
    logs_dir = root / "logs"
    if logs_dir.is_dir():
        for f in logs_dir.glob("friction-*.md"):
            miss_count += f.read_text("utf-8").count("**[miss]**")
    total = len(recs)
    rate = (adopted / total) if total else None
    return {
        "total": total, "adopted": adopted, "rate": rate,
        "miss_frictions": miss_count, "unadopted": unadopted_queries, "retries": retry_pairs,
    }


def git_revert_signals(repo: Path, limit: int = 40) -> list[str]:
    """Low-noise riverbed rollback signals (`revert`/`回退`/`撤销`) for `retro`."""
    if not (repo / ".git").exists():
        return []
    p_rev = subprocess.run(
        ["git", "-C", str(repo), "log", f"-n{limit}", "--grep=revert\\|回退\\|撤销", "-i", "--oneline"],
        capture_output=True, text=True, check=False,
    )
    return [ln.strip() for ln in p_rev.stdout.splitlines() if ln.strip()][:5]


def cmd_settle(root: Path, args: argparse.Namespace) -> int:
    today = date.today()
    uses = load_uses(root)
    open_dir = root / "open"
    to_sink: list[tuple[Path, int, float]] = []
    if open_dir.is_dir():
        for f in sorted(open_dir.glob("*.md")):
            age = _open_age_days(f, today)
            actr = actr_score(uses, f"open/{f.stem}", f.stat().st_mtime)
            if age >= args.days:
                to_sink.append((f, age, round(actr, 2)))

    # 1. Sink stale open/ into logs/underwater-YYYY-MM.md (never delete)
    print(f"## 1. 沉水候选（open/ 超过 {args.days} 天未碰）: {len(to_sink)}")
    if to_sink and args.apply:
        uw = root / "logs" / f"underwater-{today.strftime('%Y-%m')}.md"
        uw.parent.mkdir(parents=True, exist_ok=True)
        if not uw.exists():
            uw.write_text(f"# {today.strftime('%Y-%m')} · 沉水悬案（underwater_past）\n\n", encoding="utf-8")
        with uw.open("a", encoding="utf-8") as out:
            for f, age, actr in to_sink:
                out.write(f"\n<!-- underwater_from: open/{f.name} | sunk: {today} | age: {age}d | actr: {actr} -->\n")
                out.write(f.read_text("utf-8").strip() + "\n")
                f.unlink()
                print(f"  - sunk: open/{f.name} -> {uw.relative_to(root)}")
    else:
        for f, age, actr in to_sink:
            print(f"  - [dry-run] open/{f.name} (age={age}d, actr={actr})")

    # 2. Passive recall signals: adoption rate, 3-min retry pairs (forced rewording), and [miss] frictions
    st = recall_adoption_stats(root)
    rate_str = f"{st['rate']*100:.1f}%" if st["rate"] is not None else "N/A"
    print(f"\n## 2. 被动召回信号（近 {st['total']} 次采纳率 {rate_str}，换词重查 {len(st['retries'])} 对，实录漏召回 {st['miss_frictions']} 次）")
    for q1, q2 in st["retries"][:5]:
        print(f"  - 连续换词重查（强别名信号）：`{q1}` -> `{q2}`")
    for q in dict.fromkeys(st["unadopted"][:8]):
        print(f"  - 未采纳查询：{q}")
    meta_inbox = root / "_state" / "meta-inbox.md"
    if meta_inbox.is_file():
        staged = [ln for ln in meta_inbox.read_text("utf-8").splitlines() if ln.startswith("- `")]
        if staged:
            print(f"  - 跨项目暂存摩擦（`_state/meta-inbox.md`）：{len(staged)} 条待显式 `retro` 脱敏提炼")

    # 3. Low-noise git revert signals + optional transcript pointer extraction (for `retro`)
    repo = Path(getattr(args, "repo", None) or root).expanduser().resolve()
    reverts = git_revert_signals(repo)
    print(f"\n## 3. 回退与会话指针信号（供显式 `retro` 复盘，禁自动自改 | repo={repo.name}）")
    for rev in reverts:
        print(f"  - 回退记录：{rev}")
    if not reverts:
        print("  - 无近期回退记录")
    tpath = getattr(args, "transcript", None)
    if tpath:
        tp = Path(tpath).expanduser().resolve()
        if tp.is_file():
            sig = analyze_transcript(tp)
            out = write_trace_report(root, sig)
            print(
                f"  - 会话指针已生成 -> {out.relative_to(root)} "
                f"(子代理={sig.get('subagent_count', 0)}, 慢/过载子代理={len(sig.get('slow_subagents', []))}, "
                f"断流死循环={len(sig.get('interrupt_loops', []))}, 主控读二进制={len(sig.get('root_binary_reads', []))}, "
                f"等子代理偷读={sig.get('reads_while_pending', 0)}, 重跑轰炸={len(sig.get('heavy_cmd_churn', []))}, "
                f"错误={len(sig['errors'])}, 纠偏词={len(sig['corrections'])})"
            )

    # 4. Weighted blind-check sample (fact atoms without executable probes & lowest ACT-R first)
    atoms = [a for a in parse_canon_atoms(root) if a.get("nature") != "意图"]
    rng = random.Random(args.seed)
    pool = sorted(atoms, key=lambda a: (1 if "probes/" in a["anchor_text"] else 0, actr_score(uses, a["id"], a["mtime"])))
    front = pool[: min(max(args.sample * 2, 1), len(pool))]
    picked = rng.sample(front, min(args.sample, len(front))) if front else []
    print(f"\n## 4. 随机盲抽复核清单（仅抽 [事实] 原子，优先无探针/久未碰，抽 {len(picked)} 条）")
    for a in picked:
        print(f"  - [{a['id']}] {a['title']} ({a['path']})")
    return 0
