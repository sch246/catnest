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
                            reads[str(p)].append(idx)
                    elif tname == "run_command":
                        cmd = str(args.get("CommandLine") or args.get("command") or "")
                        for h in _classify_heavy_cmds(cmd):
                            heavy_cmds[h] += 1
                    elif tname == "invoke_subagent":
                        pending_roles.append(str(args.get("Role") or args.get("TypeName") or "subagent"))

            if stype != "USER_INPUT" and isinstance(content, str):
                for m in URI_RE.finditer(content):
                    cp = Path(unquote(urlparse("file://" + m.group(1)).path))
                    role = pending_roles.pop(0) if pending_roles else "subagent"
                    child_paths.append((cp, role))
                if brain_root is not None:
                    for cm in CONV_ID_RE.finditer(content):
                        cid = cm.group(1)
                        cand = brain_root / cid / ".system_generated" / "logs" / "transcript.jsonl"
                        if cand not in [x[0] for x in child_paths] and cand.is_file():
                            role = child_roles.get(cid) or (pending_roles.pop(0) if pending_roles else "subagent")
                            child_paths.append((cand, role))

            if stype == "USER_INPUT" and isinstance(content, str):
                matched = [c for c in CORRECTION_CUES if c in content]
                if matched:
                    corrections.append({"step": idx, "cues": matched})

    dur_min = round((last_dt - first_dt).total_seconds() / 60.0, 1) if (first_dt and last_dt) else 0.0
    return {
        "src_path": src_path,
        "reads": reads,
        "errors": errors,
        "oversized": oversized,
        "corrections": corrections,
        "heavy_cmds": heavy_cmds,
        "step_count": step_count,
        "duration_min": dur_min,
        "children": child_paths,
    }


def analyze_transcript(transcript_path: Path, slow_min_threshold: float = 10.0, step_threshold: int = 80) -> dict:
    root_info = _scan_single_transcript(transcript_path)
    visited: set[Path] = {root_info["src_path"].resolve()}

    total_heavy: Counter[str] = Counter(root_info["heavy_cmds"])
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
        total_heavy.update(info["heavy_cmds"])
        if info["duration_min"] >= slow_min_threshold or info["step_count"] >= step_threshold:
            cid = cp.parents[2].name if len(cp.parents) >= 3 else cp.stem
            slow_subagents.append({
                "id": cid[:8],
                "role": role[:40],
                "depth": depth,
                "duration_min": info["duration_min"],
                "steps": info["step_count"],
                "heavy": dict(info["heavy_cmds"]),
            })
        for gcp, grole in info["children"]:
            queue.append((gcp, grole, depth + 1))

    slow_subagents.sort(key=lambda x: (x["duration_min"], x["steps"]), reverse=True)
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
        "heavy_cmd_churn": heavy_churn,
        "repeated_reads": repeated_reads,
        "errors": root_info["errors"],
        "oversized": root_info["oversized"],
        "corrections": root_info["corrections"],
    }


def write_trace_report(root: Path, sig: dict) -> Path:
    lines = [
        "# _state/trace_signals.md（仅结构指针与耗时/重跑统计，供 `retro` 取证，禁入库）",
        f"- source: `{sig['transcript']}` | subagents_scanned: {sig.get('subagent_count', 0)}",
        f"- slow_subagents(>=10m|>=80steps): {len(sig.get('slow_subagents', []))} "
        f"| heavy_cmd_churn(>=3): {len(sig.get('heavy_cmd_churn', []))} "
        f"| repeated_reads(>=3): {len(sig['repeated_reads'])} | errors: {len(sig['errors'])} "
        f"| oversized(>32KB): {len(sig['oversized'])} | correction_cues: {len(sig['corrections'])}",
        "",
    ]
    if sig.get("slow_subagents"):
        lines.append("## 子代理耗时与步数膨胀告警（无需等用户抱怨自动暴露）")
        for s in sig["slow_subagents"][:15]:
            h_str = ", ".join(f"{k}={v}" for k, v in s["heavy"].items()) if s["heavy"] else "no-heavy-cmd"
            lines.append(
                f"- [慢子代理 D{s['depth']}] `{s['id']}` ({s['role']}): "
                f"**{s['duration_min']}m** / {s['steps']} steps ({h_str})"
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
        lines.append(f"- [错误/中断] step {e['step']} ({e['type']}): `{e['kind']}`")
    for o in sig["oversized"][:8]:
        lines.append(f"- [大输出 >32KB] step {o['step']} ({o['type']}): {o['bytes']}B")
    for c in sig["corrections"][:12]:
        lines.append(f"- [用户纠偏/嫌慢信号] step {c['step']}: 命中词 `{','.join(c['cues'])}`")
    out = state_dir(root) / "trace_signals.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out
