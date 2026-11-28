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

from . import actr_score, engine_root, is_unclosed_tension, load_uses, parse_canon_atoms, state_dir, touch_key
from .assemble import _format_task_collisions
from .recall import recall_task_collisions
from .trace import analyze_transcript, write_trace_report

LAST_TOUCHED_RE = re.compile(r"^last_touched:\s*(\d{4}-\d{2}-\d{2})", re.M)


def cmd_friction(root: Path, args: argparse.Namespace) -> int:
    eng_root = engine_root()
    root_resolved = root.resolve()
    now = datetime.now()
    atom_part = f" | atom: `{args.atom}`" if args.atom else ""
    ctx_part = f" | ctx: {args.context}" if args.context else ""

    if args.meta and root_resolved != eng_root:
        inbox = state_dir(eng_root) / "meta-inbox.md"
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

    target = eng_root if args.meta else root_resolved
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


def cmd_note(root: Path, args: argparse.Namespace) -> int:
    """One-way idea/constraint inbox: collide against existing nest first, then append without hijacking channel."""
    root_resolved = root.resolve()
    now = datetime.now()
    text = args.text.strip()
    top = getattr(args, "top", 5)

    # Collide BEFORE writing so the newly appended line does not match itself
    hits = recall_task_collisions(root_resolved, text, top=top) if top > 0 else []

    logs_dir = root_resolved / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    inbox_file = logs_dir / f"inbox-{now.strftime('%Y-%m')}.md"
    if not inbox_file.exists():
        inbox_file.write_text(f"# {now.strftime('%Y-%m')} · 单向想法与约束收集板\n\n", encoding="utf-8")

    ctx_part = f" | ctx: {args.context}" if getattr(args, "context", None) else ""
    entry = f"- `{now.strftime('%Y-%m-%d %H:%M')}` {text}{ctx_part}\n"
    with inbox_file.open("a", encoding="utf-8") as f:
        f.write(entry)

    opened_path: Path | None = None
    if getattr(args, "open", False):
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-")[:24] or "idea"
        opened_path = root_resolved / "open" / f"idea-{now.strftime('%m%d')}-{slug}.md"
        opened_path.parent.mkdir(parents=True, exist_ok=True)
        coll_ids = ", ".join(h["id"] for h in hits if h.get("kind") == "canon")
        coll_lines = "\n".join(
            f"- `[{h.get('nature') or h['kind']}]` {h['id']} — {h['title']} (`{h['path']}`)"
            for h in hits
        ) or "- （暂无词面命中）"
        opened_path.write_text(
            f"---\nid: I-{now.strftime('%m%d%H%M')}\ntitle: \"[未闭合] {text}\"\nstatus: active\n"
            f"last_touched: {now.strftime('%Y-%m-%d')}\ncollisions: [{coll_ids}]\n---\n\n"
            f"# [未闭合] 想法待整理：{text}\n\n"
            f"- 来源：`{inbox_file.relative_to(root_resolved)}`\n"
            f"- 现场上下文：{getattr(args, 'context', None) or '（单向收集，待整理裁决）'}\n\n"
            f"## 录入时自动碰撞到的既有约束/悬案\n{coll_lines}\n",
            encoding="utf-8",
        )
        touch_key(root_resolved, f"open/{opened_path.stem}")

    print(f"captured idea -> {inbox_file}")
    if opened_path:
        print(f"promoted unclosed card -> {opened_path}")
    if top > 0:
        print(_format_task_collisions(text, hits).lstrip("\n"))
    return 0


def gate_event_stats(root: Path) -> dict:
    """Aggregate privacy-safe gate rule counts & denominators from CATNEST_GATE_DIR/events.jsonl."""
    gate_dir = Path(os.environ.get("CATNEST_GATE_DIR") or (Path.home() / ".cache" / "catnest" / "gate"))
    ev_file = gate_dir / "events.jsonl"
    root_str = str(root.resolve())
    is_engine = root.resolve() == engine_root()
    events: Counter[str] = Counter()
    deny_rules: Counter[str] = Counter()
    bypass_rules: Counter[str] = Counter()
    break_rules: Counter[str] = Counter()
    if ev_file.is_file():
        for ln in ev_file.read_text("utf-8", errors="replace").splitlines():
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            nest = str(rec.get("nest") or "")
            if not is_engine and nest and nest != root_str:
                continue
            ev = str(rec.get("event") or "")
            rule = str(rec.get("rule") or "unspecified")
            events[ev] += 1
            if ev == "deny":
                deny_rules[rule] += 1
            elif ev in ("retry_bypass", "anchor_pass", "debt_cleaned"):
                bypass_rules[f"{rule}:{ev}"] += 1
            elif ev == "circuit_break":
                break_rules[rule] += 1
    calls = (
        events["pass"]
        + events["spawn_stamp"]
        + events["deny"]
        + events["retry_bypass"]
        + events["anchor_pass"]
    )
    return {
        "source": str(ev_file),
        "scope": "global" if is_engine else "nest",
        "calls": calls,
        "events": events,
        "deny_rules": deny_rules,
        "bypass_rules": bypass_rules,
        "break_rules": break_rules,
    }


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
    pinned_unclosed: list[tuple[Path, int]] = []
    if open_dir.is_dir():
        for f in sorted(open_dir.glob("*.md")):
            text = f.read_text("utf-8")
            age = _open_age_days(f, today)
            if age < args.days:
                continue
            # Time passing != debt resolved: unclosed tensions must NEVER auto-sink
            if is_unclosed_tension(text):
                pinned_unclosed.append((f, age))
                continue
            actr = actr_score(uses, f"open/{f.stem}", f.stat().st_mtime)
            to_sink.append((f, age, round(actr, 2)))

    # 1. Sink stale open/ into logs/underwater-YYYY-MM.md (never delete; never sink unclosed tensions)
    pin_note = f"（另有 {len(pinned_unclosed)} 条 `[未闭合]/张力` 豁免沉水）" if pinned_unclosed else ""
    print(f"## 1. 沉水候选（open/ 超过 {args.days} 天未碰）: {len(to_sink)}{pin_note}")
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
    for f, age in pinned_unclosed:
        print(f"  - [pinned-unclosed] open/{f.name} (age={age}d, 未决张力禁按时间沉水)")

    # 2. Passive recall signals
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

    # 3. Objective gate telemetry denominators (rule hits, bypasses, circuit breakers)
    gs = gate_event_stats(root)
    ev = gs["events"]
    deny_rate = f"{(ev['deny'] / gs['calls'] * 100):.1f}%" if gs["calls"] else "N/A"
    print(
        f"\n## 3. 猫闸客观分母（scope={gs['scope']} | 受管调用 {gs['calls']} 次："
        f"放行 {ev['pass']} / 注卡 {ev['spawn_stamp']} / 拦截 {ev['deny']} [{deny_rate}] / "
        f"软拦后续(绕行={ev['retry_bypass']}, 带锚={ev['anchor_pass']}, 删测={ev['debt_cleaned']}) / "
        f"熔断 {ev['circuit_break']} / 解闸 {ev['escape_phrase']}）"
    )
    for rname, cnt in gs["deny_rules"].most_common(8):
        print(f"  - 拦截规则 `{rname}`: {cnt} 次")
    for bname, cnt in gs["bypass_rules"].most_common(5):
        print(f"  - 软拦分流 `{bname}`: {cnt} 次")
    for cname, cnt in gs["break_rules"].most_common(5):
        print(f"  - 物理熔断 `{cname}`: {cnt} 次")
    if not gs["calls"] and not ev["assemble_register"]:
        print("  - 暂无已记录的猫闸事件（运行后自动写入 CATNEST_GATE_DIR/events.jsonl）")

    # 4. Low-noise git revert signals + optional transcript pointer extraction (for `retro`)
    repo = Path(getattr(args, "repo", None) or root).expanduser().resolve()
    reverts = git_revert_signals(repo)
    print(f"\n## 4. 回退与会话指针信号（供显式 `retro` 复盘，禁自动自改 | repo={repo.name}）")
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

    # 5. Weighted blind-check sample (atoms without executable probes & lowest ACT-R first)
    atoms = [a for a in parse_canon_atoms(root) if a.get("nature") != "意图"]
    rng = random.Random(args.seed)
    pool = sorted(
        atoms,
        key=lambda a: (
            1 if "probes/" in (a["anchor_text"] + " " + a.get("evidence_text", "")) else 0,
            actr_score(uses, a["id"], a["mtime"]),
        ),
    )
    front = pool[: min(max(args.sample * 2, 1), len(pool))]
    picked = rng.sample(front, min(args.sample, len(front))) if front else []
    print(f"\n## 5. 随机盲抽复核清单（优先无机器探针/久未碰，抽 {len(picked)} 条）")
    for a in picked:
        print(f"  - [{a['id']}] ({a.get('nature') or '?'}) {a['title']} ({a['path']})")
    return 0
