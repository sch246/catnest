"""Privacy-safe session transcript signal extractor for `retro` (pointers & timing/churn metrics only, zero raw prose)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import state_dir

CORRECTION_CUES = (
    "不对", "不是", "我说的", "错了", "停下", "不要试图", "显然不是", "反了",
    "好慢", "太慢", "这么慢", "太久", "好久", "卡了",
)

HEAVY_CMD_RULES: tuple[tuple[str, re.Pattern[str], re.Pattern[str] | None], ...] = (
    ("full_mvn_test", re.compile(r"\bmvn(?:\.cmd)?\b[^\n]*\btest\b"), re.compile(r"-Dtest=")),
    ("mvn_package", re.compile(r"\bmvn(?:\.cmd)?\b[^\n]*\bpackage\b"), None),
    ("full_vitest", re.compile(r"\bvitest\s+run\b"), re.compile(r"\.(?:test|spec)\.[jt]sx?\b")),
    ("vite_build", re.compile(r"\b(?:build:prod|vite\s+build)\b"), None),
    ("codex_exec", re.compile(r"\bcodex\s+exec\b"), re.compile(r"--help\b")),
    ("git_bundle", re.compile(r"\bgit\b[^\n]*\bbundle\s+create\b"), None),
    ("worktree_add", re.compile(r"\bgit\b[^\n]*\bworktree\s+add\b"), None),
)

URI_RE = re.compile(r"file://(/[^\s\"'<>]+/transcript(?:_full)?\.jsonl)")
CONV_ID_RE = re.compile(r'"conversationId"\s*:\s*"([0-9a-fA-F-]{20,})"')
SENDER_RE = re.compile(r"\bsender=([0-9a-fA-F-]{20,})\b")
BINARY_EXT_RE = re.compile(r"\.(?:png|jpe?g|webp|gif|bmp|pdf|zip|tar|gz|jar|mp4|mov)$", re.I)


def _pick_transcript_file(p: Path) -> Path:
    full_cand = p.with_name("transcript_full.jsonl")
    return full_cand if (p.name == "transcript.jsonl" and full_cand.is_file()) else p


def _parse_iso(ts: str) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _classify_heavy_cmds(cmd: str) -> list[str]:
    hits: list[str] = []
    for name, pos_re, neg_re in HEAVY_CMD_RULES:
        if pos_re.search(cmd) and (neg_re is None or not neg_re.search(cmd)):
            hits.append(name)
    return hits


def _scan_single_transcript(transcript_path: Path) -> dict:
    src_path = _pick_transcript_file(transcript_path)
    reads: dict[str, list[int]] = defaultdict(list)
    errors: list[dict] = []
    oversized: list[dict] = []
    corrections: list[dict] = []
    heavy_cmds: Counter[str] = Counter()
    child_roles: dict[str, str] = {}
    pending_roles: list[str] = []
    child_paths: list[tuple[Path, str]] = []
    binary_read_steps: list[int] = []
    pending_binary_results = 0
    interrupt_dts: list[datetime] = []
    interrupt_steps: list[int] = []
    active_subagents: set[str] = set()
    pending_launches = 0
    reads_while_pending = 0

    brain_root: Path | None = None
    # Typical layout: <brain>/<conv-id>/.system_generated/logs/transcript.jsonl
    if len(src_path.parents) >= 3 and src_path.parent.name == "logs" and src_path.parents[1].name == ".system_generated":
        brain_root = src_path.parents[3]

    first_dt: datetime | None = None
    last_dt: datetime | None = None
    step_count = 0

    with src_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                step = json.loads(raw)
            except ValueError:
                continue
            step_count += 1
            idx = step.get("step_index", -1)
            stype = step.get("type", "")
            status = step.get("status", "")
            content = step.get("content") or ""
            dt = _parse_iso(step.get("created_at") or "")
            if dt is not None:
                if first_dt is None or dt < first_dt:
                    first_dt = dt
                if last_dt is None or dt > last_dt:
                    last_dt = dt

            if stype == "ERROR_MESSAGE" or status == "ERROR":
                err_kind = str(step.get("error") or content)[:60].splitlines()[0] if (step.get("error") or content) else "ERROR"
                err_kind = re.sub(r"/[^\s]+", "<path>", err_kind)
                errors.append({"step": idx, "type": stype, "kind": err_kind})
                if "stream was interrupted" in str(content).lower():
                    interrupt_steps.append(idx)
                    if dt is not None:
                        interrupt_dts.append(dt)

            if isinstance(content, str):
                if "Showing binary file of type " in content:
                    if pending_binary_results > 0:
                        pending_binary_results -= 1
                    else:
                        binary_read_steps.append(idx)
                for sm in SENDER_RE.finditer(content):
                    active_subagents.discard(sm.group(1))

            nbytes = len(content.encode("utf-8", errors="ignore")) if isinstance(content, str) else 0
            if stype != "USER_INPUT" and nbytes > 32768:
                oversized.append({"step": idx, "bytes": nbytes, "type": stype})

            if stype == "PLANNER_RESPONSE":
                for tc in step.get("tool_calls") or []:
                    tname = tc.get("name") or ""
                    args = tc.get("args") or tc.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    if tname == "read_file":
                        p = args.get("Path") or args.get("path")
                        if p:
                            p_str = str(p)
                            reads[p_str].append(idx)
                            if BINARY_EXT_RE.search(p_str):
                                binary_read_steps.append(idx)
                                pending_binary_results += 1
                            if active_subagents or pending_launches > 0:
                                reads_while_pending += 1
                    elif tname == "run_command":
                        cmd = str(args.get("CommandLine") or args.get("command") or "")
                        for h in _classify_heavy_cmds(cmd):
                            heavy_cmds[h] += 1
                    elif tname == "invoke_subagent":
                        pending_roles.append(str(args.get("Role") or args.get("TypeName") or "subagent"))
                        pending_launches += 1

            if stype != "USER_INPUT" and isinstance(content, str):
                for m in URI_RE.finditer(content):
                    cp = Path(unquote(urlparse("file://" + m.group(1)).path))
                    role = pending_roles.pop(0) if pending_roles else "subagent"
                    child_paths.append((cp, role))
                    if len(cp.parents) >= 3:
                        active_subagents.add(cp.parents[2].name)
                    pending_launches = max(0, pending_launches - 1)
                if brain_root is not None:
                    for cm in CONV_ID_RE.finditer(content):
                        cid = cm.group(1)
                        active_subagents.add(cid)
                        pending_launches = max(0, pending_launches - 1)
                        cand = brain_root / cid / ".system_generated" / "logs" / "transcript.jsonl"
                        if cand not in [x[0] for x in child_paths] and cand.is_file():
                            role = child_roles.get(cid) or (pending_roles.pop(0) if pending_roles else "subagent")
                            child_paths.append((cand, role))

            if stype == "USER_INPUT" and isinstance(content, str):
                matched = [c for c in CORRECTION_CUES if c in content]
                if matched:
                    corrections.append({"step": idx, "cues": matched})

    dur_min = round((last_dt - first_dt).total_seconds() / 60.0, 1) if (first_dt and last_dt) else 0.0
    int_wasted = round((interrupt_dts[-1] - interrupt_dts[0]).total_seconds() / 60.0, 1) if len(interrupt_dts) >= 2 else 0.0
    return {
        "src_path": src_path,
        "reads": reads,
        "distinct_reads": len(reads),
        "binary_read_steps": binary_read_steps,
        "reads_while_pending": reads_while_pending,
        "interrupt_count": len(interrupt_steps),
        "interrupt_wasted_min": int_wasted,
        "errors": errors,
        "oversized": oversized,
        "corrections": corrections,
        "heavy_cmds": heavy_cmds,
        "step_count": step_count,
        "duration_min": dur_min,
        "children": child_paths,
    }


def analyze_transcript(transcript_path: Path, slow_min_threshold: float = 10.0, step_threshold: int = 80, read_threshold: int = 40) -> dict:
    root_info = _scan_single_transcript(transcript_path)
    visited: set[Path] = {root_info["src_path"].resolve()}

    total_heavy: Counter[str] = Counter(root_info["heavy_cmds"])
    all_errors: list[dict] = list(root_info["errors"])
    interrupt_loops: list[dict] = []
    if root_info["interrupt_count"] >= 3:
        interrupt_loops.append({
            "id": "root",
            "role": "main",
            "count": root_info["interrupt_count"],
            "wasted_min": root_info["interrupt_wasted_min"],
        })
    subagent_count = 0
    slow_subagents: list[dict] = []

    queue: list[tuple[Path, str, int]] = [(cp, role, 1) for cp, role in root_info["children"]]
    while queue:
        cp, role, depth = queue.pop(0)
        if not cp.is_file():
            continue
        real_cp = _pick_transcript_file(cp).resolve()
        if real_cp in visited:
            continue
        visited.add(real_cp)
        subagent_count += 1
        info = _scan_single_transcript(cp)
        cid = cp.parents[2].name if len(cp.parents) >= 3 else cp.stem
        short_id = cid[:8]
        total_heavy.update(info["heavy_cmds"])
        for e in info["errors"]:
            all_errors.append({**e, "agent": short_id})
        if info["interrupt_count"] >= 3:
            interrupt_loops.append({
                "id": short_id,
                "role": role[:40],
                "count": info["interrupt_count"],
                "wasted_min": info["interrupt_wasted_min"],
            })
        if info["duration_min"] >= slow_min_threshold or info["step_count"] >= step_threshold or info["distinct_reads"] >= read_threshold:
            slow_subagents.append({
                "id": short_id,
                "role": role[:40],
                "depth": depth,
                "duration_min": info["duration_min"],
                "steps": info["step_count"],
                "distinct_reads": info["distinct_reads"],
                "heavy": dict(info["heavy_cmds"]),
            })
        for gcp, grole in info["children"]:
            queue.append((gcp, grole, depth + 1))

    slow_subagents.sort(key=lambda x: (x["duration_min"], x["steps"], x["distinct_reads"]), reverse=True)
    repeated_reads = [
        {"path": p, "count": len(steps), "steps": steps}
        for p, steps in sorted(root_info["reads"].items(), key=lambda kv: len(kv[1]), reverse=True)
        if len(steps) >= 3
    ]
    heavy_churn = [
        {"kind": k, "total": v, "root": root_info["heavy_cmds"].get(k, 0), "subagents": v - root_info["heavy_cmds"].get(k, 0)}
        for k, v in total_heavy.most_common()
        if v >= 3
    ]
    return {
        "transcript": str(transcript_path),
        "subagent_count": subagent_count,
        "slow_subagents": slow_subagents,
        "interrupt_loops": interrupt_loops,
        "root_binary_reads": root_info["binary_read_steps"],
        "root_distinct_reads": root_info["distinct_reads"],
        "reads_while_pending": root_info["reads_while_pending"],
        "heavy_cmd_churn": heavy_churn,
        "repeated_reads": repeated_reads,
        "errors": all_errors,
        "oversized": root_info["oversized"],
        "corrections": root_info["corrections"],
    }


def write_trace_report(root: Path, sig: dict) -> Path:
    lines = [
        "# _state/trace_signals.md（仅结构指针与耗时/重跑统计，供 `retro` 取证，禁入库）",
        f"- source: `{sig['transcript']}` | subagents_scanned: {sig.get('subagent_count', 0)}",
        f"- slow_or_overloaded_subagents: {len(sig.get('slow_subagents', []))} "
        f"| interrupt_loops(>=3): {len(sig.get('interrupt_loops', []))} "
        f"| root_binary_reads: {len(sig.get('root_binary_reads', []))} "
        f"| reads_while_pending: {sig.get('reads_while_pending', 0)} "
        f"| root_distinct_reads: {sig.get('root_distinct_reads', 0)}",
        f"- heavy_cmd_churn(>=3): {len(sig.get('heavy_cmd_churn', []))} "
        f"| repeated_reads(>=3): {len(sig['repeated_reads'])} | errors: {len(sig['errors'])} "
        f"| oversized(>32KB): {len(sig['oversized'])} | correction_cues: {len(sig['corrections'])}",
        "",
    ]
    if sig.get("interrupt_loops"):
        lines.append("## 断流死循环告警（`stream was interrupted` >= 3）")
        for il in sig["interrupt_loops"]:
            lines.append(
                f"- [断流死循环] `{il['id']}` ({il['role']}): 连断 **{il['count']}** 次，空烧 **{il['wasted_min']}m**"
            )
        lines.append("")
    if sig.get("root_binary_reads") or sig.get("reads_while_pending", 0) >= 3 or sig.get("root_distinct_reads", 0) > 15:
        lines.append("## 主控角色越界直读信号（二进制/等子代理期间下场直读）")
        if sig.get("root_binary_reads"):
            lines.append(f"- [主控直读图片/二进制] 共 **{len(sig['root_binary_reads'])}** 次 @ steps {sig['root_binary_reads'][:20]}")
        if sig.get("reads_while_pending", 0) >= 3:
            lines.append(f"- [等子代理期间下场直读] 主控在后台子代理未返回时调用 `read_file` **{sig['reads_while_pending']}** 次")
        if sig.get("root_distinct_reads", 0) > 15:
            lines.append(f"- [主控直读文件过多] 主控累计直读 **{sig['root_distinct_reads']}** 个不同文件")
        lines.append("")
    if sig.get("slow_subagents"):
        lines.append("## 子代理耗时、步数与读文件过载告警")
        for s in sig["slow_subagents"][:15]:
            h_str = ", ".join(f"{k}={v}" for k, v in s["heavy"].items()) if s["heavy"] else "no-heavy-cmd"
            lines.append(
                f"- [慢/过载子代理 D{s['depth']}] `{s['id']}` ({s['role']}): "
                f"**{s['duration_min']}m** / {s['steps']} steps / {s.get('distinct_reads', 0)} files ({h_str})"
            )
        lines.append("")
    if sig.get("heavy_cmd_churn"):
        lines.append("## 重型构建/全量测试/盲审重复轰炸统计")
        for h in sig["heavy_cmd_churn"]:
            lines.append(
                f"- [重跑轰炸] `{h['kind']}`: 共 **{h['total']}** 次 (root={h['root']}, subagents={h['subagents']})"
            )
        lines.append("")
    for r in sig["repeated_reads"][:8]:
        lines.append(f"- [重复读 {r['count']}次] `{r['path']}` @ steps {r['steps']}")
    for e in sig["errors"][:8]:
        ag = f"[{e['agent']}] " if e.get("agent") else ""
        lines.append(f"- [错误/中断] {ag}step {e['step']} ({e['type']}): `{e['kind']}`")
    for o in sig["oversized"][:8]:
        lines.append(f"- [大输出 >32KB] step {o['step']} ({o['type']}): {o['bytes']}B")
    for c in sig["corrections"][:12]:
        lines.append(f"- [用户纠偏/嫌慢信号] step {c['step']}: 命中词 `{','.join(c['cues'])}`")
    out = state_dir(root) / "trace_signals.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out
