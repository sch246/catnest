"""Privacy-safe session transcript signal extractor for `retro` (pointers only, zero raw prose)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from . import state_dir

CORRECTION_CUES = ("不对", "不是", "我说的", "错了", "停下", "不要试图", "显然不是", "反了")


def analyze_transcript(transcript_path: Path) -> dict:
    # Prefer sibling transcript_full.jsonl so >32KB detection reflects real payload size, not 4KB compact preview
    full_cand = transcript_path.with_name("transcript_full.jsonl")
    src_path = full_cand if (transcript_path.name == "transcript.jsonl" and full_cand.is_file()) else transcript_path

    reads: dict[str, list[int]] = defaultdict(list)
    errors: list[dict] = []
    oversized: list[dict] = []
    corrections: list[dict] = []

    with src_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                step = json.loads(raw)
            except ValueError:
                continue
            idx = step.get("step_index", -1)
            stype = step.get("type", "")
            status = step.get("status", "")
            content = step.get("content") or ""

            if stype == "ERROR_MESSAGE" or status == "ERROR":
                err_kind = str(step.get("error") or content)[:60].splitlines()[0] if (step.get("error") or content) else "ERROR"
                err_kind = re.sub(r"/[^\s]+", "<path>", err_kind)
                errors.append({"step": idx, "type": stype, "kind": err_kind})

            nbytes = len(content.encode("utf-8", errors="ignore")) if isinstance(content, str) else 0
            if stype != "USER_INPUT" and nbytes > 32768:
                oversized.append({"step": idx, "bytes": nbytes, "type": stype})

            if stype == "PLANNER_RESPONSE":
                for tc in step.get("tool_calls") or []:
                    if tc.get("name") == "read_file":
                        args = tc.get("args") or tc.get("arguments") or {}
                        p = args.get("Path") or args.get("path")
                        if p:
                            reads[str(p)].append(idx)

            if stype == "USER_INPUT" and isinstance(content, str):
                matched = [c for c in CORRECTION_CUES if c in content]
                if matched:
                    corrections.append({"step": idx, "cues": matched})

    repeated_reads = [
        {"path": p, "count": len(steps), "steps": steps}
        for p, steps in sorted(reads.items(), key=lambda kv: len(kv[1]), reverse=True)
        if len(steps) >= 3
    ]
    return {
        "transcript": str(transcript_path),
        "repeated_reads": repeated_reads,
        "errors": errors,
        "oversized": oversized,
        "corrections": corrections,
    }


def write_trace_report(root: Path, sig: dict) -> Path:
    lines = [
        "# _state/trace_signals.md（仅结构指针，供 `retro` 回原会话按 step 取证，禁入库）",
        f"- source: `{sig['transcript']}`",
        f"- repeated_reads(>=3): {len(sig['repeated_reads'])} | errors: {len(sig['errors'])} "
        f"| oversized/truncated: {len(sig['oversized'])} | correction_cues: {len(sig['corrections'])}",
        "",
    ]
    for r in sig["repeated_reads"][:8]:
        lines.append(f"- [重复读 {r['count']}次] `{r['path']}` @ steps {r['steps']}")
    for e in sig["errors"][:8]:
        lines.append(f"- [错误/中断] step {e['step']} ({e['type']}): `{e['kind']}`")
    for o in sig["oversized"][:8]:
        lines.append(f"- [大输出 >32KB] step {o['step']} ({o['type']}): {o['bytes']}B")
    for c in sig["corrections"][:10]:
        lines.append(f"- [用户纠偏信号] step {c['step']}: 命中词 `{','.join(c['cues'])}`")
    out = state_dir(root) / "trace_signals.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out
