#!/usr/bin/env python3
"""Antigravity lifecycle hook (`PreToolUse` & `PreInvocation`) for catnest: capability-based fail-closed gate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
from pathlib import Path

STAMP_ANY_RE = re.compile(r"\[CATNEST-GATE\s+[^\]]*\]\s*")
ROLE_CARD_BLOCK_RE = re.compile(r"\[CATNEST-ROLE\b[^\]]*\].*?\[/CATNEST-ROLE\]\s*", re.S)
STAMP_RE = re.compile(
    r"\[CATNEST-GATE\s+role=(deputy|worker|tentacle)\s+nest=(\S+?)(?:\s+parent=(\S+?))?\s+nonce=([0-9a-f]{12,64})\s*\]"
)
ROLE_HINT_RE = re.compile(r"(?:--role\s+|role=)(deputy|worker|tentacle)\b")
UNSAFE_SHELL_RE = re.compile(r"[|><$`]")
BINARY_EXT_RE = re.compile(r"\.(?:png|jpe?g|webp|gif|bmp|pdf|zip|tar|gz|jar|mp4|mov|pyc|class|sqlite3?|db)$", re.I)
CONV_ID_RE = re.compile(r'"conversationId"\s*:\s*"([0-9a-fA-F-]{20,})"')
URI_CONV_RE = re.compile(r"file://[^\s\"'<>]+/([0-9a-fA-F-]{20,})/\.system_generated/logs/transcript")
SENDER_RE = re.compile(r"\bsender=([0-9a-fA-F-]{20,})\b")
BOARD_DONE_AGENT_RE = re.compile(r'"agent"\s*:\s*"([a-z0-9_-]+)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"')
DONE_TAG_RE = re.compile(r"\[done\]", re.I)
CODE_EXT_RE = re.compile(r"\.(?:py|java|kt|ts|tsx|js|jsx|mjs|cjs|go|rs|cpp|cc|c|cs|rb|php|swift)$", re.I)
TEST_FILE_PATH_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?|spec)/|"
    r"(?:^|/)test_[^/]+\.[A-Za-z0-9]+$|"
    r"(?:Test|Tests|Spec|Specs)\.[A-Za-z0-9]+$|"
    r"\.(?:test|spec)\.[A-Za-z0-9]+$",
    re.I,
)
BRIEF_TEST_MENTION_RE = re.compile(
    r"(?:\*Test\*|\*\.test\.\*|\*\.spec\.\*|"
    r"\b[A-Za-z0-9_-]+(?:Test|Tests)\.(?:java|kt|ts|tsx|js|jsx|py)\b|"
    r"\b[A-Za-z0-9_.-]+\.(?:test|spec)\.(?:ts|tsx|js|jsx|mjs|cjs)\b|"
    r"\btest_[A-Za-z0-9_]+\.py\b)",
    re.I,
)
NEGATION_LINE_RE = re.compile(r"(?:严禁|禁止|禁写|禁增|不得|不要|无需|不用|勿|免写|without|do\s+not|don't|no\s+(?:new\s+)?(?:mock|unit|self))", re.I)
EXTERNAL_ANCHOR_RE = re.compile(
    r"(?:外部实尺|外部锚|外部真值|独立真值|存量同步|既有测试同步|契约同步|实测标本|协议帧|真实模板|负向副作用|"
    r"external[\s_-]*(?:oracle|anchor)|existing[\s_-]*test[\s_-]*sync)",
    re.I,
)
TEST_DEBT_TAG_RE = re.compile(r"\[猫闸客观审计\s*·\s*测试负债:")
CMD_DIR_HINT_RE = re.compile(r"(?:(?:^|[;&\n]\s*)cd\s+|git\s+-C\s+)(?:\"([^\"]+)\"|'([^']+)'|(\S+))")

ALLOWED_MAIN_TOOLS = {
    "invoke_subagent", "send_message", "manage_subagents", "manage_task",
    "schedule", "ask_question", "swarm", "read_board", "post_message", "swarm_wait",
}
ALLOWED_CATNEST_CMDS = {"status", "recall", "assemble", "touch", "check", "friction", "purr", "settle"}
MUTATING_TOOLS = {"run_command", "write_file", "edit_file"}
SPAWN_TOOLS = {"invoke_subagent", "define_subagent", "run_workflow"}
ASSEMBLE_VALUE_FLAGS = {"--role", "--task", "--max-lines", "--root"}


def _engine_root() -> Path:
    return Path(os.environ.get("CATNEST_HOME") or Path(__file__).resolve().parent.parent).expanduser().resolve()


def gate_cache_dir() -> Path:
    base = Path(os.environ.get("CATNEST_GATE_DIR") or (Path.home() / ".cache" / "catnest" / "gate"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _load_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def _save_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def load_policy(nest_root: Path | None = None) -> dict:
    cfg = _load_json(_engine_root() / "roles.json")
    defaults = {
        "escape_phrase": "解除猫闸",
        "session_ttl_sec": 86400,
        "max_continuations": 3,
        "max_interrupts_total": 3,
        "warn_interrupts_total": 2,
        "max_denials_streak": 5,
        "warn_denials_streak": 3,
        "bytes_per_token_fallback": 4,
        "test_debt_gate_enabled": True,
        "test_debt_line_threshold": 30,
        **(cfg.get("defaults") or {}),
    }
    roles = dict(cfg.get("roles") or {})
    if nest_root is not None:
        ov = _load_json(nest_root / "roles.json")
        if ov:
            defaults.update(ov.get("defaults") or {})
            for rname, rspec in (ov.get("roles") or {}).items():
                roles[rname] = {**roles.get(rname, {}), **rspec}
    return {"defaults": defaults, "roles": roles}


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _issue_stamp(child_role: str, nest_root: Path, parent_cid: str) -> str:
    nonce = secrets.token_hex(8)
    _save_json(gate_cache_dir() / f"nonce_{nonce}.json", {
        "nonce": nonce,
        "role": child_role,
        "nest_root": str(nest_root.resolve()),
        "parent": parent_cid,
        "created_at": time.time(),
    })
    return f"[CATNEST-GATE role={child_role} nest={nest_root.resolve()} parent={parent_cid} nonce={nonce}]\n"


def _verify_stamp(role: str | None, nest_str: str | None, nonce: str | None, ttl: int) -> bool:
    if not role or not nest_str or not nonce:
        return False
    rec = _load_json(gate_cache_dir() / f"nonce_{nonce}.json")
    if not rec or time.time() - rec.get("created_at", 0) > ttl:
        return False
    return rec.get("role") == role and str(Path(rec.get("nest_root", "")).resolve()) == str(Path(nest_str).resolve())


def _split_subcommands(cmd: str) -> list[str] | None:
    cleaned = re.sub(r"(?:^|(?<=[\s;&]))2>&1(?=$|[\s;&])", "", cmd)
    if UNSAFE_SHELL_RE.search(cleaned):
        return None
    if "&" in re.sub(r"&&", "", cleaned):
        return None
    subs = [s.strip() for s in re.split(r"(?:\n|;|&&)+", cleaned) if s.strip()]
    return subs or None


def detect_assemble_nest(cmd: str, cwd: str) -> Path | None:
    subs = _split_subcommands(cmd)
    if not subs:
        return None
    cur_cwd = Path(cwd or ".")
    for sub in subs:
        try:
            parts = shlex.split(sub)
        except ValueError:
            return None
        if not parts:
            continue
        if parts[0] == "cd" and len(parts) == 2:
            nxt = Path(parts[1]).expanduser()
            cur_cwd = nxt if nxt.is_absolute() else (cur_cwd / nxt)
            continue
        idx = next((i for i, tok in enumerate(parts) if tok.endswith("catnest.py")), -1)
        if idx < 0:
            continue
        rest = parts[idx + 1 :]
        if "assemble" not in rest or "--list" in rest or "--files-only" in rest:
            continue
        role_val = None
        root_val = None
        pos_after_asm: list[str] = []
        seen_asm = False
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok == "assemble" and not seen_asm:
                seen_asm = True
                i += 1
                continue
            if tok in ASSEMBLE_VALUE_FLAGS:
                val = rest[i + 1] if i + 1 < len(rest) else ""
                if tok == "--role":
                    role_val = val
                elif tok == "--root":
                    root_val = val
                i += 2
                continue
            if tok.startswith("--role="):
                role_val = tok.split("=", 1)[1]
            elif tok.startswith("--root="):
                root_val = tok.split("=", 1)[1]
            elif not tok.startswith("-") and seen_asm:
                pos_after_asm.append(tok)
            i += 1
        if role_val in ("deputy", "worker", "tentacle") or not pos_after_asm:
            continue
        base = Path(root_val).expanduser() if root_val else cur_cwd
        if not base.is_absolute():
            base = cur_cwd / base
        return base.resolve()
    return None


def _is_allowed_single_main_subcommand(parts: list[str]) -> bool:
    if not parts:
        return False
    head = parts[0]
    if head == "cd":
        return len(parts) == 2
    if head in ("echo", "true"):
        return True
    if Path(head).name.startswith("python"):
        cat_idx = next((i for i, tok in enumerate(parts[1:], 1) if tok.endswith("catnest.py")), -1)
        if cat_idx < 0:
            return False
        for py_flag in parts[1:cat_idx]:
            if py_flag in ("-c", "-m") or py_flag.startswith("-c"):
                return False
        rest = parts[cat_idx + 1 :]
        if any(tok == "--install-hook" or tok.startswith("--install-hook=") for tok in rest):
            return False
        i = 0
        subcmd = None
        while i < len(rest):
            tok = rest[i]
            if tok == "--root":
                if i + 1 >= len(rest):
                    return False
                i += 2
                continue
            if tok.startswith("--root=") or tok.startswith("-"):
                i += 1
                continue
            subcmd = tok
            break
        return bool(subcmd and subcmd != "init" and subcmd in ALLOWED_CATNEST_CMDS)
    if head == "git" and len(parts) >= 4 and parts[1] == "-C":
        git_rest = parts[3:]
        gsub = git_rest[0]
        if gsub in ("status", "log", "diff", "show", "fetch"):
            return True
        if gsub == "worktree" and len(git_rest) >= 2:
            wsub = git_rest[1]
            if wsub == "list":
                return True
            if wsub == "add":
                return "--detach" in git_rest[2:]
            if wsub == "remove":
                return len(git_rest) >= 3
        return False
    return False


def is_allowed_main_command(cmd: str) -> bool:
    subs = _split_subcommands(cmd)
    if not subs:
        return False
    for sub in subs:
        try:
            parts = shlex.split(sub)
        except ValueError:
            return False
        if not _is_allowed_single_main_subcommand(parts):
            return False
    return True


def _resolve_transcript_path(transcript_path: str, prefer_full: bool = False) -> Path | None:
    if not transcript_path:
        return None
    p = Path(transcript_path)
    if prefer_full:
        full = p.with_name("transcript_full.jsonl")
        if full.is_file():
            return full
    if p.is_file():
        return p
    alt = p.with_name("transcript.jsonl")
    return alt if alt.is_file() else None


def estimate_context_tokens(transcript_path: str, bytes_per_token: int = 4) -> int:
    """Read latest step `input_tokens + cache_read_tokens` (plus trailing bytes) or fall back to file_size // 4."""
    p = _resolve_transcript_path(transcript_path, prefer_full=False)
    if p is None:
        return 0
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > 131072:
                fh.seek(size - 131072)
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
        trailing_bytes = 0
        for raw in reversed(tail):
            if not raw.strip():
                continue
            try:
                st = json.loads(raw)
            except ValueError:
                trailing_bytes += len(raw.encode("utf-8", errors="ignore"))
                continue
            usage = st.get("usage") if isinstance(st.get("usage"), dict) else {}
            in_tok = st.get("input_tokens") if st.get("input_tokens") is not None else usage.get("input_tokens")
            cache_tok = st.get("cache_read_tokens") if st.get("cache_read_tokens") is not None else usage.get("cache_read_tokens")
            if in_tok is not None or cache_tok is not None:
                out_tok = int(st.get("output_tokens") or usage.get("output_tokens") or 0)
                base = int(in_tok or 0) + int(cache_tok or 0) + out_tok
                return base + (trailing_bytes // max(bytes_per_token, 1))
            trailing_bytes += len(raw.encode("utf-8", errors="ignore"))
    except Exception:
        pass
    full = _resolve_transcript_path(transcript_path, prefer_full=True) or p
    try:
        return int(full.stat().st_size // max(bytes_per_token, 1))
    except Exception:
        return 0


def inspect_transcript_role(transcript_path: str) -> tuple[bool, str | None, str | None, str | None, str | None]:
    """Scan initial messages before first `PLANNER_RESPONSE` (covers 2-line swarm boot)."""
    p = _resolve_transcript_path(transcript_path)
    if p is None:
        return True, None, None, None, None
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for idx in range(10):
                line = fh.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                obj = json.loads(line)
                stype = obj.get("type", "")
                if stype == "PLANNER_RESPONSE":
                    if idx == 0:
                        return False, None, None, None, None
                    break
                if stype == "USER_INPUT" or obj.get("source") == "USER_EXPLICIT":
                    return True, None, None, None, None
                content = str(obj.get("content") or "")
                m = STAMP_RE.search(content)
                if m:
                    return (
                        False,
                        m.group(1),
                        m.group(2).strip(),
                        m.group(3).strip() if m.group(3) else None,
                        m.group(4).strip(),
                    )
        return False, None, None, None, None
    except Exception:
        return True, None, None, None, None


def _is_catnest_interrupt_event(st: dict) -> bool:
    if st.get("type") != "ERROR_MESSAGE" and st.get("status") != "ERROR":
        return False
    message = str(st.get("content") or st.get("error") or "").lower()
    if "stream was interrupted" not in message:
        return False
    return "猫闸断路器" not in message and "猫闸断流熔断" not in message


def _has_interrupt_breaker_after_latest_interrupt(transcript_path: str) -> bool:
    p = _resolve_transcript_path(transcript_path)
    if p is None:
        return False
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > 65536:
                fh.seek(size - 65536)
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for raw in reversed(lines):
            if not raw.strip():
                continue
            try:
                st = json.loads(raw)
            except ValueError:
                continue
            message = str(st.get("content") or st.get("error") or "")
            if "猫闸断路器" in message:
                return True
            if _is_catnest_interrupt_event(st):
                return False
    except Exception:
        pass
    return False


def count_total_interrupts(transcript_path: str) -> int:
    """Count real cumulative `stream was interrupted` errors across the session."""
    p = _resolve_transcript_path(transcript_path)
    if p is None:
        return 0
    total = 0
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if "stream was interrupted" not in raw.lower():
                    continue
                try:
                    st = json.loads(raw)
                except ValueError:
                    continue
                if _is_catnest_interrupt_event(st):
                    total += 1
    except Exception:
        pass
    return total


def has_recent_interrupt(transcript_path: str) -> bool:
    """Return True iff `stream was interrupted` occurred after the latest non-error `PLANNER_RESPONSE`."""
    p = _resolve_transcript_path(transcript_path)
    if p is None:
        return False
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > 65536:
                fh.seek(size - 65536)
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        user_turns_after = 0
        for raw in reversed(lines):
            if not raw.strip():
                continue
            try:
                st = json.loads(raw)
            except ValueError:
                continue
            stype = st.get("type", "")
            is_err = stype == "ERROR_MESSAGE" or st.get("status") == "ERROR"
            if _is_catnest_interrupt_event(st):
                return True
            if stype == "PLANNER_RESPONSE" and not is_err:
                return False
            if stype == "USER_INPUT" or st.get("source") == "USER_EXPLICIT":
                user_turns_after += 1
                if user_turns_after > 1:
                    return False
    except Exception:
        pass
    return False


def has_posted_done_in_transcript(transcript_path: str) -> bool:
    p = _resolve_transcript_path(transcript_path)
    if p is None:
        return False
    pending_done = False
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    st = json.loads(raw)
                except ValueError:
                    continue
                stype = st.get("type", "")
                if stype == "PLANNER_RESPONSE":
                    if pending_done:
                        return True
                    for tc in st.get("tool_calls") or []:
                        if tc.get("name") == "post_message":
                            targs = tc.get("args") or tc.get("arguments") or {}
                            if isinstance(targs, str):
                                try:
                                    targs = json.loads(targs)
                                except ValueError:
                                    targs = {}
                            if DONE_TAG_RE.search(str(targs.get("text") or "")):
                                pending_done = True
                                break
                elif pending_done:
                    content = str(st.get("content") or "")
                    if (
                        "猫闸出口软拦截" in content
                        or "Blocked by catnest gate" in content
                        or '"decision": "deny"' in content
                    ):
                        pending_done = False
                    elif '"posted"' in content or '"seq"' in content:
                        return True
    except Exception:
        pass
    return pending_done


def has_active_children(transcript_path: str, st: dict) -> bool:
    """Detect active/running child subagents, working swarm members, or same-turn spawn (`派出即停`)."""
    if st.get("spawn_in_current_turn"):
        return True
    if st.get("active_children"):
        return True
    p = _resolve_transcript_path(transcript_path)
    if p is None:
        return False
    active_subs: set[str] = set()
    active_swarm: set[str] = set()
    pending_invoke = 0
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    step = json.loads(raw)
                except ValueError:
                    continue
                stype = step.get("type", "")
                content = str(step.get("content") or "")
                if stype == "PLANNER_RESPONSE":
                    for tc in step.get("tool_calls") or []:
                        nm = tc.get("name") or ""
                        targs = tc.get("args") or tc.get("arguments") or {}
                        if isinstance(targs, str):
                            try:
                                targs = json.loads(targs)
                            except ValueError:
                                targs = {}
                        if nm == "invoke_subagent":
                            pending_invoke += 1
                        elif nm == "swarm":
                            act = str(targs.get("action") or "")
                            wname = str(targs.get("name") or "").strip()
                            if act == "add" and wname:
                                tasks = targs.get("tasks")
                                n_copy = int(targs.get("n") or 1)
                                if isinstance(tasks, list) and len(tasks) > 0:
                                    for idx in range(1, len(tasks) + 1):
                                        active_swarm.add(f"{wname}-{idx}")
                                elif n_copy > 1:
                                    for idx in range(1, n_copy + 1):
                                        active_swarm.add(f"{wname}-{idx}")
                                else:
                                    active_swarm.add(wname)
                            elif act == "kill" and wname:
                                active_swarm.discard(wname)
                elif stype != "USER_INPUT" and content:
                    if "Blocked by catnest gate" in content or '"decision": "deny"' in content:
                        pending_invoke = max(0, pending_invoke - 1)
                    for cm in CONV_ID_RE.finditer(content):
                        active_subs.add(cm.group(1))
                        pending_invoke = max(0, pending_invoke - 1)
                    for um in URI_CONV_RE.finditer(content):
                        active_subs.add(um.group(1))
                        pending_invoke = max(0, pending_invoke - 1)
                    for sm in SENDER_RE.finditer(content):
                        active_subs.discard(sm.group(1))
                    for bm in BOARD_DONE_AGENT_RE.finditer(content):
                        ag, txt = bm.group(1), bm.group(2)
                        if DONE_TAG_RE.search(txt):
                            active_swarm.discard(ag)
                    if '"members"' in content and '"working"' not in content and '"running"' not in content:
                        active_swarm.clear()
    except Exception:
        return False
    return bool(pending_invoke > 0 or active_subs or active_swarm)


def _find_registered_nest_for_cwd(cwd: str, ttl: int) -> Path | None:
    cur = Path(cwd or ".").expanduser().resolve()
    now = time.time()
    best: tuple[float, Path] | None = None
    for mf in gate_cache_dir().glob("main_*.json"):
        st = _load_json(mf)
        upd = float(st.get("updated_at") or 0)
        if not st or now - upd > ttl or not st.get("nest_root"):
            continue
        nr = Path(st["nest_root"]).expanduser().resolve()
        ws_cands = [nr]
        if nr.name.startswith("."):
            ws_cands.append(nr.parent.resolve())
        if st.get("workspace_root"):
            ws_cands.append(Path(st["workspace_root"]).expanduser().resolve())
        if any(_is_within(cur, w) for w in ws_cands):
            if best is None or upd > best[0]:
                best = (upd, nr)
    return best[1] if best else None


def resolve_session_context(payload: dict) -> dict | None:
    cid = str(payload.get("conversationId") or "")
    if not cid:
        return None
    cache = gate_cache_dir()
    base_pol = load_policy()
    defs = base_pol["defaults"]
    ttl = int(defs["session_ttl_sec"])
    last_input = str(payload.get("lastUserInput") or "")
    escape = os.environ.get("CATNEST_GATE_ESCAPE") or defs["escape_phrase"]
    main_file = cache / f"main_{cid}.json"
    if escape and escape in last_input:
        main_file.unlink(missing_ok=True)
        return None

    tpath = str(payload.get("transcriptPath") or "")
    cwd = str(payload.get("cwd") or ".")
    is_root, s_role, s_nest, s_parent, s_nonce = inspect_transcript_role(tpath)
    if is_root:
        st = _load_json(main_file)
        if not st or time.time() - st.get("updated_at", 0) > ttl:
            return None
        nr = Path(st["nest_root"])
        return {"role": "main", "nest_root": nr, "parent": None, "state_path": main_file, "state": st, "policy": load_policy(nr)}

    sub_file = cache / f"sub_{cid}.json"
    existing = _load_json(sub_file)
    if existing and existing.get("verified") and time.time() - existing.get("updated_at", time.time()) <= ttl:
        nr = Path(existing["nest_root"])
        return {
            "role": existing["role"], "nest_root": nr, "parent": existing.get("parent"),
            "state_path": sub_file, "state": existing, "policy": load_policy(nr),
        }

    if s_role and s_nest and _verify_stamp(s_role, s_nest, s_nonce, ttl):
        nr = Path(s_nest).resolve()
        st = existing or {"tool_count": 0, "denied_streak": 0, "read_calls": 0, "read_bytes": 0, "created_at": time.time()}
        st.setdefault("created_at", time.time())
        st.update({"role": s_role, "nest_root": str(nr), "parent": s_parent, "verified": True, "updated_at": time.time()})
        if s_role == "worker":
            _record_touched_repo(st, Path(cwd or "."))
        _save_json(sub_file, st)
        return {"role": s_role, "nest_root": nr, "parent": s_parent, "state_path": sub_file, "state": st, "policy": load_policy(nr)}

    # Fail-closed: any non-root session inside a registered catnest workspace defaults to `worker`
    fallback_nest = _find_registered_nest_for_cwd(cwd, ttl)
    if fallback_nest is None:
        return None
    st = existing or {"tool_count": 0, "denied_streak": 0, "read_calls": 0, "read_bytes": 0, "created_at": time.time()}
    st.setdefault("created_at", time.time())
    st.update({"role": "worker", "nest_root": str(fallback_nest), "parent": s_parent, "verified": False, "updated_at": time.time()})
    _record_touched_repo(st, Path(cwd or "."))
    _save_json(sub_file, st)
    return {"role": "worker", "nest_root": fallback_nest, "parent": s_parent, "state_path": sub_file, "state": st, "policy": load_policy(fallback_nest)}


def _run_git(repo_dir: Path, git_args: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), *git_args],
            capture_output=True, text=True, timeout=2, check=False,
        )
        return proc.stdout if proc.returncode == 0 else None
    except Exception:
        return None


def _is_test_code_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").lstrip("./")
    if not norm or norm.startswith("probes/") or "/probes/" in norm:
        return False
    return bool(CODE_EXT_RE.search(norm) and TEST_FILE_PATH_RE.search(norm))


def _record_touched_repo(st: dict, target_path: Path) -> None:
    try:
        cand = target_path.expanduser()
        if not cand.exists():
            cand = cand.parent
        if not cand.exists():
            return
        cand_dir = cand.resolve() if cand.is_dir() else cand.resolve().parent
    except Exception:
        return
    repos: dict[str, str] = st.setdefault("touched_repos", {})
    for existing_root in repos:
        if _is_within(cand_dir, Path(existing_root)):
            return
    top = _run_git(cand_dir, ["rev-parse", "--show-toplevel"])
    if not top:
        return
    repo_root = str(Path(top.strip()).resolve())
    if repo_root not in repos:
        head = _run_git(Path(repo_root), ["rev-parse", "HEAD"])
        repos[repo_root] = head.strip() if head else ""


def _record_repos_from_command(st: dict, cmd: str, cwd: str) -> None:
    base_cwd = Path(cwd or ".").expanduser()
    for m in CMD_DIR_HINT_RE.finditer(cmd):
        raw_d = next((g for g in m.groups() if g), "")
        if not raw_d:
            continue
        p = Path(raw_d).expanduser()
        if not p.is_absolute():
            p = base_cwd / p
        _record_touched_repo(st, p)


def _inspect_worker_test_debt(cwd: str, st: dict) -> dict:
    repos: dict[str, str] = dict(st.get("touched_repos") or {})
    cwd_path = Path(cwd or ".").expanduser()
    if cwd_path.exists():
        top = _run_git(cwd_path.resolve(), ["rev-parse", "--show-toplevel"])
        if top:
            repos.setdefault(str(Path(top.strip()).resolve()), "")

    new_files: list[str] = []
    touched_files: dict[str, tuple[int, int]] = {}
    created_at = float(st.get("created_at") or 0)

    for repo_str, base_head in repos.items():
        repo = Path(repo_str)
        if not repo.is_dir():
            continue
        diff_ref: list[str] = [base_head] if base_head else ["HEAD"]
        numstat = _run_git(repo, ["diff", "--numstat", *diff_ref])
        namestat = _run_git(repo, ["diff", "--name-status", *diff_ref])
        if not base_head and not (numstat or "").strip():
            # Fallback when worker committed before state captured base_head
            ct = _run_git(repo, ["log", "-1", "--format=%ct"])
            if ct and created_at and float(ct.strip() or 0) >= created_at - 5:
                parent_ok = _run_git(repo, ["rev-parse", "--verify", "HEAD~1"])
                if parent_ok:
                    numstat = _run_git(repo, ["diff", "--numstat", "HEAD~1..HEAD"])
                    namestat = _run_git(repo, ["diff", "--name-status", "HEAD~1..HEAD"])
                else:
                    numstat = _run_git(repo, ["show", "--numstat", "--format=", "HEAD"])
                    namestat = _run_git(repo, ["show", "--name-status", "--format=", "HEAD"])

        added_set: set[str] = set()
        for ln in (namestat or "").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2 and parts[0].startswith("A"):
                rel = parts[-1].strip()
                if _is_test_code_path(rel):
                    added_set.add(rel)

        for ln in (numstat or "").splitlines():
            parts = ln.split("\t")
            if len(parts) < 3:
                continue
            add_s, del_s, rel = parts[0].strip(), parts[1].strip(), parts[-1].strip()
            if not _is_test_code_path(rel):
                continue
            add_n = int(add_s) if add_s.isdigit() else 0
            del_n = int(del_s) if del_s.isdigit() else 0
            prev_a, prev_d = touched_files.get(rel, (0, 0))
            touched_files[rel] = (prev_a + add_n, prev_d + del_n)
            if rel in added_set and rel not in new_files:
                new_files.append(rel)

        untracked = _run_git(repo, ["ls-files", "--others", "--exclude-standard"])
        for rel in (untracked or "").splitlines():
            rel = rel.strip()
            if not _is_test_code_path(rel):
                continue
            fp = repo / rel
            if not fp.is_file():
                continue
            try:
                line_cnt = len(fp.read_text("utf-8", errors="replace").splitlines())
            except Exception:
                line_cnt = 0
            prev_a, prev_d = touched_files.get(rel, (0, 0))
            touched_files[rel] = (prev_a + line_cnt, prev_d)
            if rel not in new_files:
                new_files.append(rel)

    total_added = sum(a for a, _ in touched_files.values())
    total_deleted = sum(d for _, d in touched_files.values())
    net_lines = max(0, total_added - total_deleted)
    names = sorted(touched_files)
    summary = ", ".join(Path(n).name for n in names[:4])
    if len(names) > 4:
        summary += f" 等{len(names)}个"
    return {
        "new_test_files": new_files,
        "added_lines": total_added,
        "deleted_lines": total_deleted,
        "net_lines": net_lines,
        "touched_count": len(names),
        "file_summary": summary,
    }


def _check_dispatch_test_debt(
    role: str, child_role: str, tname: str, args: dict, text: str,
    pol: dict, st: dict, st_path: Path,
) -> dict | None:
    defs = pol.get("defaults") or {}
    if role != "main" or child_role != "worker" or not defs.get("test_debt_gate_enabled", True):
        return None
    if EXTERNAL_ANCHOR_RE.search(text):
        return None
    hits: list[str] = []
    for ln in text.splitlines():
        if NEGATION_LINE_RE.search(ln):
            continue
        for m in BRIEF_TEST_MENTION_RE.finditer(ln):
            tok = m.group(0)
            if tok not in hits:
                hits.append(tok)
    if not hits:
        return None
    target_id = str(args.get("name") or args.get("Role") or "")
    sig = hashlib.sha1(f"{tname}:{target_id}:{','.join(sorted(hits))}".encode("utf-8")).hexdigest()[:12]
    warned: list[str] = list(st.get("warned_test_dispatches") or [])
    if sig in warned:
        return None
    warned.append(sig)
    st["warned_test_dispatches"] = warned[-20:]
    sample = ", ".join(hits[:4])
    return _deny_with_streak(
        st, st_path,
        f"猫闸入口软拦截（反自证单测）：派给 `worker` 的任务单分配了测试文件（{sample}），但未声明实现外真值来源。"
        "请移除无必要的测试所有权（改报编译结果），或在派单中显式写明「外部实尺: <来源>」/「存量同步: <理由>」；"
        "若确需如此，原样重试一次即放行。",
    )


def _deny_with_streak(st: dict, st_path: Path, reason: str) -> dict:
    st["denied_streak"] = st.get("denied_streak", 0) + 1
    st["updated_at"] = time.time()
    _save_json(st_path, st)
    return {"action": "deny", "reason": reason}


def _allow_reset_streak(st: dict, st_path: Path) -> dict:
    st["denied_streak"] = 0
    st["updated_at"] = time.time()
    _save_json(st_path, st)
    return {"action": "pass"}


def _infer_child_role(text: str, sub_type: str = "", role_arg: str = "") -> str:
    combined = f"{role_arg}\n{text}"
    m = ROLE_HINT_RE.search(combined)
    if m:
        return m.group(1)
    if sub_type == "research":
        return "tentacle"
    return "worker"


def _estimate_read_bytes(rp: Path, args: dict) -> int:
    if not rp.is_file():
        return 0
    size = rp.stat().st_size
    s_line = args.get("StartLine")
    e_line = args.get("EndLine")
    if s_line is not None or e_line is not None:
        try:
            lines = rp.read_text("utf-8", errors="replace").splitlines(keepends=True)
            start = max(int(s_line or 1) - 1, 0)
            end = int(e_line) if e_line is not None else len(lines)
            chunk = "".join(lines[start:end]).encode("utf-8", errors="ignore")
            return min(len(chunk), 46080)
        except Exception:
            return min(size, 46080)
    return size


def _is_handoff_write(rp: Path, nest_root: Path, art_dir: str, args: dict) -> bool:
    body = str(args.get("Content") or args.get("Replacement") or "")
    if len(body.splitlines()) > 120 or len(body) > 8192:
        return False
    return (
        _is_within(rp, nest_root / "open")
        or _is_within(rp, nest_root / "_state" / "dig")
        or _is_within(rp, nest_root / "logs")
        or (bool(art_dir) and _is_within(rp, Path(art_dir)))
    )


def _render_child_role_card(child_role: str, pol: dict) -> str:
    rspec = (pol.get("roles") or {}).get(child_role) or {}
    bullets = rspec.get("bullets") or []
    if not bullets:
        return ""
    lines: list[str] = []
    for b in bullets:
        try:
            lines.append(f"- {b.format_map(rspec)}")
        except Exception:
            lines.append(f"- {b}")
    return f"[CATNEST-ROLE role={child_role}]\n" + "\n".join(lines) + "\n[/CATNEST-ROLE]\n"


def _build_dispatch_text(child_role: str, nest_root: Path, parent_cid: str, pol: dict, clean_body: str) -> str:
    stamp = _issue_stamp(child_role, nest_root, parent_cid)
    if f"--- [ROLE: {child_role}] ---" in clean_body:
        return stamp + clean_body
    card = _render_child_role_card(child_role, pol)
    return f"{stamp}{card}\n{clean_body}" if card else f"{stamp}{clean_body}"


def _handle_spawn_tool(
    cid: str, role: str, rspec: dict, pol: dict, tname: str, args: dict,
    nest_root: Path, st: dict, st_path: Path,
) -> dict | None:
    is_swarm_mut = tname == "swarm" and str(args.get("action") or "") in ("add", "kill", "model", "title")
    is_swarm_add = tname == "swarm" and str(args.get("action") or "") == "add"
    if tname not in SPAWN_TOOLS and not is_swarm_mut:
        return None
    if not rspec.get("can_spawn", False):
        return _deny_with_streak(st, st_path, f"猫闸拦截：`{role}` 禁止派生子代理（0 spawn），请只答当前窄问题并回传。")
    if not is_swarm_add and tname not in SPAWN_TOOLS:
        return None

    if tname == "invoke_subagent":
        raw_prompt = str(args.get("Prompt") or "")
        sub_type = str(args.get("TypeName") or "")
        role_arg = str(args.get("Role") or "")
        clean_prompt = ROLE_CARD_BLOCK_RE.sub("", STAMP_ANY_RE.sub("", raw_prompt)).lstrip()
        child_role = _infer_child_role(clean_prompt, sub_type=sub_type, role_arg=role_arg)
        warn_res = _check_dispatch_test_debt(role, child_role, tname, args, clean_prompt, pol, st, st_path)
        if warn_res is not None:
            return warn_res
        new_prompt = _build_dispatch_text(child_role, nest_root, cid, pol, clean_prompt)
        overwrites: dict = {"Prompt": new_prompt}
        req_model = str(args.get("Model") or "").strip()
        child_default = ((pol.get("roles") or {}).get(child_role) or {}).get("default_model")
        if child_default and (not req_model or req_model == "inherit"):
            overwrites["Model"] = child_default
        if role == "main":
            st["spawn_in_current_turn"] = True
        st["denied_streak"] = 0
        st["updated_at"] = time.time()
        _save_json(st_path, st)
        return {"action": "overwrite", "overwrite": overwrites}

    if is_swarm_add:
        raw_brief = str(args.get("brief") or "")
        clean_brief = ROLE_CARD_BLOCK_RE.sub("", STAMP_ANY_RE.sub("", raw_brief)).lstrip()
        child_role = _infer_child_role(clean_brief, role_arg=str(args.get("name") or ""))
        warn_res = _check_dispatch_test_debt(role, child_role, tname, args, clean_brief, pol, st, st_path)
        if warn_res is not None:
            return warn_res
        new_brief = _build_dispatch_text(child_role, nest_root, cid, pol, clean_brief)
        if role == "main":
            st["spawn_in_current_turn"] = True
        st["denied_streak"] = 0
        st["updated_at"] = time.time()
        _save_json(st_path, st)
        return {"action": "overwrite", "overwrite": {"brief": new_brief}}

    if role == "main":
        st["spawn_in_current_turn"] = True
    return _allow_reset_streak(st, st_path)


def _eval_main_tool(
    payload: dict, pol: dict, rspec: dict, defs: dict, tname: str, args: dict,
    nest_root: Path, cwd: str, st: dict, st_path: Path,
) -> dict:
    tpath = str(payload.get("transcriptPath") or "")
    if tname == "send_message":
        recip = str(args.get("Recipient") or "")
        cont = st.setdefault("continuations", {})
        sent_count = int(cont.get(recip, 0)) if recip else 0
        max_cont = int(defs.get("max_continuations", 3))
        child_tokens = 0
        child_hard_tokens = None
        if recip and tpath:
            tp = Path(tpath)
            if len(tp.parents) >= 4:
                child_tp = tp.parents[3] / recip / ".system_generated" / "logs" / "transcript.jsonl"
                child_tokens = estimate_context_tokens(str(child_tp), int(defs.get("bytes_per_token_fallback", 4)))
                _, child_role, _, _, _ = inspect_transcript_role(str(child_tp))
                child_role = child_role or "worker"
                child_spec = (pol.get("roles") or {}).get(child_role) or {}
                child_hard_tokens = child_spec.get("hard_tokens")
        if (recip and sent_count >= max_cont) or (
            child_hard_tokens is not None and child_tokens >= int(child_hard_tokens)
        ):
            return _deny_with_streak(
                st, st_path,
                f"猫闸拦截：向子代理 `{recip[:8]}` 续塞已达上限（续塞 {sent_count}/{max_cont} 次, "
                f"~{child_tokens}/{child_hard_tokens} tokens）。"
                "会话即抛：请写交接至 `open/<切片>.md` 并新开干净子代理接棒。",
            )
        if recip:
            cont[recip] = sent_count + 1
        return _allow_reset_streak(st, st_path)

    if tname in ALLOWED_MAIN_TOOLS:
        return _allow_reset_streak(st, st_path)

    if tname == "read_file":
        raw_p = str(args.get("Path") or args.get("path") or "")
        if not raw_p:
            return _allow_reset_streak(st, st_path)
        if not rspec.get("allow_binary_read", False) and BINARY_EXT_RE.search(raw_p):
            return _deny_with_streak(
                st, st_path,
                "猫闸拦截：主控严禁直读图片/PDF/二进制文件。请派 `tentacle`（TypeName='research'）查看并回传 ≤20 行结论。",
            )
        p = Path(raw_p).expanduser()
        if not p.is_absolute():
            p = Path(cwd) / p
        rp = p.resolve()
        art_dir = str(payload.get("artifactDirectoryPath") or "")
        in_nest_md = (
            _is_within(rp, nest_root)
            and rp.suffix.lower() == ".md"
            and not _is_within(rp, nest_root / "field-evidence")
        )
        in_skill_or_art = (bool(art_dir) and _is_within(rp, Path(art_dir))) or rp.name == "SKILL.md"
        if in_nest_md or in_skill_or_art:
            return _allow_reset_streak(st, st_path)

        # Business file read: enforce `派出即停` first!
        if rspec.get("block_read_while_children_active", True) and has_active_children(tpath, st):
            return _deny_with_streak(
                st, st_path,
                "猫闸拦截（派出即停）：当前存在运行中的未归子代理或本轮刚发出派单，严禁主控在等待期间偷读业务文件！请结束回合等待唤醒。",
            )

        max_files = int(rspec.get("direct_read_max_files") or 3)
        max_bytes = int(rspec.get("direct_read_max_file_bytes") or 32768)
        if not rp.is_file():
            return _deny_with_streak(st, st_path, "猫闸拦截：主控仅允许直读已知存在的小文本路径，未知路径请派 `tentacle` 查证。")
        if BINARY_EXT_RE.search(raw_p):
            # Allowed binary (screenshots) is for verifying evidence before writing truth; it is not
            # business-code exploration, so it skips the text byte cap and file quota.
            return _allow_reset_streak(st, st_path)
        if _estimate_read_bytes(rp, args) > max_bytes:
            return _deny_with_streak(
                st, st_path,
                f"猫闸拦截：目标文件超过主控直读上限（>{max_bytes // 1024}KB），请传行号小范围读取或派 `tentacle`。",
            )
        seen_files: list[str] = list(st.get("direct_read_files") or [])
        rp_str = str(rp)
        if rp_str not in seen_files:
            if len(seen_files) >= max_files:
                return _deny_with_streak(
                    st, st_path,
                    f"猫闸拦截：主控已知路径业务直读已达上限（{max_files}/{max_files} 个文件），其余问题请派 `tentacle` 或 `deputy`。",
                )
            seen_files.append(rp_str)
            st["direct_read_files"] = seen_files
        return _allow_reset_streak(st, st_path)

    if tname in ("write_file", "edit_file"):
        raw_p = str(args.get("Path") or args.get("path") or "")
        p = Path(raw_p).expanduser()
        if not p.is_absolute():
            p = Path(cwd) / p
        rp = p.resolve()
        art_dir = str(payload.get("artifactDirectoryPath") or "")
        if rp.suffix.lower() == ".md" and (_is_within(rp, nest_root) or (art_dir and _is_within(rp, Path(art_dir)))):
            return _allow_reset_streak(st, st_path)
        return _deny_with_streak(
            st, st_path,
            "猫闸拦截：主控只允许编辑猫窝/制品目录下的 *.md，业务源码与探针修改请派 `worker` 或 `deputy`。",
        )

    if tname == "run_command":
        cmd = str(args.get("CommandLine") or args.get("command") or "")
        if is_allowed_main_command(cmd):
            return _allow_reset_streak(st, st_path)
        return _deny_with_streak(
            st, st_path,
            "猫闸拦截：主控仅允许运行纯 `catnest.py` 管理命令与猫窝 `git status/log/diff`，执行/构建请派 `worker` 或 `tentacle`。",
        )

    return _deny_with_streak(st, st_path, f"猫闸拦截：主控禁用 `{tname}` 直接探测，请交由 `tentacle` 或 `deputy`。")


def _eval_subagent_tool(
    payload: dict, role: str, rspec: dict, defs: dict, parent_cid: str | None,
    tname: str, args: dict, nest_root: Path, cwd: str, st: dict, st_path: Path,
) -> dict:
    tpath = str(payload.get("transcriptPath") or "")
    art_dir = str(payload.get("artifactDirectoryPath") or "")

    # 1. Cumulative stream-interrupt circuit breaker (>=3 across session)
    total_int = count_total_interrupts(tpath)
    if total_int >= int(defs.get("max_interrupts_total", 3)):
        if tname in ("post_message", "swarm_wait"):
            return _allow_reset_streak(st, st_path)
        return _deny_with_streak(
            st, st_path,
            f"猫闸断流熔断：当前会话累计发生 {total_int} 次 `stream was interrupted`（>=3），禁止继续读写或执行空烧，请立即交卷退役。",
        )

    # 2. One-shot operator rule (`worker` retired after posting `[done]`)
    done_already = bool(st.get("done_posted")) or (bool(rspec.get("one_shot_done")) and has_posted_done_in_transcript(tpath))
    if done_already and rspec.get("one_shot_done"):
        st["done_posted"] = True
        if tname in ("post_message", "swarm_wait", "read_board", "manage_task"):
            return _allow_reset_streak(st, st_path)
        return _deny_with_streak(
            st, st_path,
            "猫闸一次性算子熔断：该 worker 已发送过 `[done]` 退役，严禁跨任务复用执行读写或命令！请回复提示协调者调用 `swarm add` 启动干净新会话。",
        )

    if tname == "post_message":
        msg_text = str(args.get("text") or "")
        if DONE_TAG_RE.search(msg_text):
            if role == "worker" and defs.get("test_debt_gate_enabled", True):
                debt = _inspect_worker_test_debt(cwd, st)
                threshold = int(rspec.get("test_debt_line_threshold") or defs.get("test_debt_line_threshold") or 30)
                if debt["new_test_files"] or debt["net_lines"] > threshold:
                    new_cnt = len(debt["new_test_files"])
                    if not EXTERNAL_ANCHOR_RE.search(msg_text) and not st.get("test_debt_challenged"):
                        st["test_debt_challenged"] = True
                        return _deny_with_streak(
                            st, st_path,
                            f"猫闸出口软拦截（反自证单测 · 测试负债 +{debt['net_lines']} 行）：检测到新建测试文件 {new_cnt} 个 / "
                            f"测试净增 +{debt['net_lines']} 行（{debt['file_summary']}），但交卷消息未写明实现外真值来源。"
                            "请优先删除自证 Mock 测试仅留编译验证，或在 `[done]` 中补写「外部实尺: <来源>」/「存量同步: <理由>」与三档口径后重发。",
                        )
                    st["done_posted"] = True
                    st["tool_count"] = int(st.get("tool_count", 0)) + 1
                    st["denied_streak"] = 0
                    st["updated_at"] = time.time()
                    _save_json(st_path, st)
                    if not TEST_DEBT_TAG_RE.search(msg_text):
                        audit_line = (
                            f"\n\n[猫闸客观审计 · 测试负债: +{debt['net_lines']}行"
                            f" | 新建测试文件 {new_cnt} 个 ({debt['file_summary']})]"
                        )
                        return {"action": "overwrite", "overwrite": {"text": msg_text + audit_line}}
                    return {"action": "pass"}
            st["done_posted"] = True
        st["tool_count"] = int(st.get("tool_count", 0)) + 1
        return _allow_reset_streak(st, st_path)

    if tname == "send_message":
        recip = str(args.get("Recipient") or "")
        if recip == "parent" or (parent_cid and recip == parent_cid):
            return _deny_with_streak(st, st_path, "子代理完工请直接输出纯文本结束回合，勿向父会话调 send_message。")
        return _allow_reset_streak(st, st_path)

    if tname in ("manage_subagents", "manage_task", "swarm_wait", "read_board"):
        return _allow_reset_streak(st, st_path)

    # 3. Hard token watermark check
    hard_tokens = rspec.get("hard_tokens")
    cur_tokens = estimate_context_tokens(tpath, int(defs.get("bytes_per_token_fallback", 4)))
    if hard_tokens is not None and cur_tokens >= int(hard_tokens):
        if tname in ("write_file", "edit_file"):
            raw_p = str(args.get("Path") or args.get("path") or "")
            p = Path(raw_p).expanduser()
            rp = (p if p.is_absolute() else (Path(cwd) / p)).resolve()
            if rspec.get("write_scope") == "dig_only":
                ok_write = _is_within(rp, nest_root / "_state" / "dig") and len(str(args.get("Content") or "")) <= 8192
            else:
                ok_write = _is_handoff_write(rp, nest_root, art_dir, args)
            if ok_write:
                return _allow_reset_streak(st, st_path)
        return _deny_with_streak(
            st, st_path,
            f"猫闸硬水位熔断（{role}: ~{cur_tokens} >= {hard_tokens} tokens）：严禁继续 `read_file` 或执行探索命令！"
            "仅放行向 `open/` 或 `_state/dig/` 写入交接记录，并发送 `[done]` 交卷退役。",
        )

    # 4. Role-specific write scope (`tentacle` = `_state/dig/` only)
    if tname in ("write_file", "edit_file") and rspec.get("write_scope") == "dig_only":
        raw_p = str(args.get("Path") or args.get("path") or "")
        p = Path(raw_p).expanduser()
        rp = (p if p.is_absolute() else (Path(cwd) / p)).resolve()
        body = str(args.get("Content") or args.get("Replacement") or "")
        if not _is_within(rp, nest_root / "_state" / "dig") or len(body.splitlines()) > 120:
            return _deny_with_streak(
                st, st_path,
                "猫闸拦截：`tentacle` 窄触手禁止修改业务文件，仅允许向 `_state/dig/` 分批短写（≤120 行）。",
            )

    # 5. Role-specific `read_file` binary ban & call/byte quotas (`deputy` & `tentacle`)
    if tname == "read_file":
        raw_p = str(args.get("Path") or args.get("path") or "")
        if raw_p and not rspec.get("allow_binary_read", True) and BINARY_EXT_RE.search(raw_p):
            return _deny_with_streak(
                st, st_path,
                f"猫闸拦截：`{role}` 严禁直读 PNG/图片/二进制文件，请扇出 `tentacle` 子代理查看并回传结论。",
            )
        max_calls = rspec.get("direct_read_max_calls")
        max_total_bytes = rspec.get("direct_read_max_total_bytes")
        used_calls = int(st.get("read_calls", 0))
        used_bytes = int(st.get("read_bytes", 0))
        p = Path(raw_p).expanduser() if raw_p else Path(cwd)
        rp = (p if p.is_absolute() else (Path(cwd) / p)).resolve()
        est_b = _estimate_read_bytes(rp, args) if raw_p else 0
        if max_calls is not None and used_calls >= int(max_calls):
            hint = "请扇出 `tentacle` 子代理并行查证！" if role == "deputy" else "请立即汇总已核实河岸 + 未查清单回传！"
            return _deny_with_streak(
                st, st_path,
                f"猫闸拦截：`{role}` 直读次数已达上限（{used_calls}/{max_calls} 次），{hint}",
            )
        if max_total_bytes is not None and (used_bytes + est_b > int(max_total_bytes)):
            return _deny_with_streak(
                st, st_path,
                f"猫闸拦截：`{role}` 累计直读字节超上限（{used_bytes + est_b}/{max_total_bytes}B，上限 48KB），请扇出 `tentacle` 查证！",
            )
        st["read_calls"] = used_calls + 1
        st["read_bytes"] = used_bytes + est_b

    # 6. Track touched git repos for worker exit test-debt audit (covers cross-worktree edits & shell writes)
    if role == "worker" and defs.get("test_debt_gate_enabled", True):
        if tname in ("write_file", "edit_file"):
            raw_p = str(args.get("Path") or args.get("path") or "")
            if raw_p:
                p = Path(raw_p).expanduser()
                rp = (p if p.is_absolute() else (Path(cwd) / p))
                _record_touched_repo(st, rp.parent)
        elif tname == "run_command":
            _record_repos_from_command(st, str(args.get("CommandLine") or args.get("command") or ""), cwd)

    st["tool_count"] = int(st.get("tool_count", 0)) + 1
    return _allow_reset_streak(st, st_path)


def evaluate_pre_tool(payload: dict) -> dict:
    cid = str(payload.get("conversationId") or "")
    cwd = str(payload.get("cwd") or ".")
    tc = payload.get("toolCall") or {}
    tname = str(tc.get("name") or "")
    args = tc.get("args") or {}
    tpath = str(payload.get("transcriptPath") or "")

    # Auto-register root session on `catnest.py assemble <recipe>` while preserving `continuations` & quotas!
    if tname == "run_command" and cid:
        cmd = str(args.get("CommandLine") or args.get("command") or "")
        is_root, _, _, _, _ = inspect_transcript_role(tpath)
        if is_root:
            nest = detect_assemble_nest(cmd, cwd)
            if nest is not None and (nest / "boot.md").is_file() and is_allowed_main_command(cmd):
                main_path = gate_cache_dir() / f"main_{cid}.json"
                prev = _load_json(main_path)
                prev.update({
                    "nest_root": str(nest),
                    "workspace_root": str(Path(cwd or ".").expanduser().resolve()),
                    "updated_at": time.time(),
                    "denied_streak": 0,
                })
                prev.setdefault("continuations", {})
                prev.setdefault("direct_read_files", [])
                _save_json(main_path, prev)
                return {"action": "pass"}

    ctx = resolve_session_context(payload)
    if ctx is None:
        return {"action": "pass"}

    role = ctx["role"]
    nest_root: Path = ctx["nest_root"]
    parent_cid: str | None = ctx.get("parent")
    st = ctx["state"]
    st_path: Path = ctx["state_path"]
    pol = ctx["policy"]
    defs = pol["defaults"]
    rspec = (pol.get("roles") or {}).get(role) or {}

    # Check hard watermark / retirement BEFORE allowing subagents to spawn further children
    if role != "main":
        hard_tok = rspec.get("hard_tokens")
        cur_tok = estimate_context_tokens(tpath, int(defs.get("bytes_per_token_fallback", 4)))
        retired = bool(st.get("done_posted")) or (bool(rspec.get("one_shot_done")) and has_posted_done_in_transcript(tpath))
        if retired and (tname in SPAWN_TOOLS or (tname == "swarm" and args.get("action") == "add")):
            return _deny_with_streak(st, st_path, "猫闸一次性算子熔断：已 `[done]` 退役的 worker 禁止再派生子代理。")
        if hard_tok is not None and cur_tok >= int(hard_tok) and (tname in SPAWN_TOOLS or (tname == "swarm" and args.get("action") == "add")):
            return _deny_with_streak(st, st_path, f"猫闸硬水位熔断（~{cur_tok} >= {hard_tok} tokens）：超水位禁止继续派生，请写交接并交卷。")

    spawn_res = _handle_spawn_tool(cid, role, rspec, pol, tname, args, nest_root, st, st_path)
    if spawn_res is not None:
        return spawn_res

    if role == "main":
        return _eval_main_tool(payload, pol, rspec, defs, tname, args, nest_root, cwd, st, st_path)
    return _eval_subagent_tool(payload, role, rspec, defs, parent_cid, tname, args, nest_root, cwd, st, st_path)


def evaluate_pre_invocation(payload: dict) -> dict:
    tpath = str(payload.get("transcriptPath") or "")
    is_root, _, _, _, _ = inspect_transcript_role(tpath)
    ctx = resolve_session_context(payload)
    defs = (ctx["policy"]["defaults"] if ctx else load_policy()["defaults"])
    sys_notes: list[str] = []

    if is_root:
        # Never cumulatively warn or terminate the user's root conversation window; only gently nudge right after an interrupt
        if has_recent_interrupt(tpath):
            sys_notes.append(
                "【断流恢复提示】上一步刚发生 `stream was interrupted`，继续时请避免重复长篇推演或整文件重写，优先分步短写。"
            )
    else:
        total_int = count_total_interrupts(tpath)
        max_int = int(defs.get("max_interrupts_total", 3))
        warn_int = int(defs.get("warn_interrupts_total", 2))
        if total_int >= max_int:
            already_reported = _has_interrupt_breaker_after_latest_interrupt(tpath)
            return {
                "inject_system": None,
                "inject_error": None if already_reported else (
                    f"猫闸断路器：检测到子会话累计 {total_int} 次 `stream was interrupted`（>={max_int}），已自动熔断止损。"
                ),
                "terminate": True,
            }
        if total_int >= warn_int:
            sys_notes.append(
                f"【猫闸断流预警】当前子会话已累计 {total_int} 次 `stream was interrupted`（满 {max_int} 次即硬熔断）！"
                "严禁长思考或整文件重写：请拆成每次 ≤80 行短写，或直接用 ≤10 行纯文本交卷！"
            )

    if ctx is None:
        return {"inject_system": "\n".join(sys_notes) if sys_notes else None, "inject_error": None, "terminate": False}

    role = ctx["role"]
    st = ctx["state"]
    st_path: Path = ctx["state_path"]
    pol = ctx["policy"]
    defs = pol["defaults"]
    rspec = (pol.get("roles") or {}).get(role) or {}

    if role == "main" and st.get("spawn_in_current_turn"):
        st["spawn_in_current_turn"] = False
        _save_json(st_path, st)

    denied = int(st.get("denied_streak", 0))
    if denied >= int(defs.get("max_denials_streak", 5)):
        st["denied_streak"] = 0
        _save_json(st_path, st)
        return {
            "inject_system": None,
            "inject_error": "猫闸熔断：当前代理连续 5 次撞击越界工具禁令，已终止本轮循环。",
            "terminate": True,
        }
    if denied >= int(defs.get("warn_denials_streak", 3)):
        sys_notes.append("【猫闸强警告】你已连续 3 次撞击角色边界禁令！请立即遵守分权契约或直接收尾交卷。")

    if role != "main":
        if rspec.get("one_shot_done") and (st.get("done_posted") or has_posted_done_in_transcript(tpath)):
            st["done_posted"] = True
            _save_json(st_path, st)
            sys_notes.append("【猫闸退役提醒】你已发送过 `[done]`，属于已退役一次性算子：禁止接新活读写文件，请回复协调者 `swarm add` 干净新会话并 `swarm_wait`。")
        else:
            cur_tok = estimate_context_tokens(tpath, int(defs.get("bytes_per_token_fallback", 4)))
            soft_tok = rspec.get("soft_tokens")
            hard_tok = rspec.get("hard_tokens")
            if hard_tok is not None and cur_tok >= int(hard_tok):
                sys_notes.append(f"【猫闸硬水位告警】上下文已达 ~{cur_tok} tokens（>={hard_tok}），仅允许写交接记录与发 `[done]` 立即退役！")
            elif soft_tok is not None and cur_tok >= int(soft_tok):
                sys_notes.append(f"【猫闸软水位提醒】上下文已达 ~{cur_tok} tokens（软水位 {soft_tok} / 硬水位 {hard_tok}），请尽快收尾交卷，勿铺新摊子。")

    return {"inject_system": "\n".join(sys_notes) if sys_notes else None, "inject_error": None, "terminate": False}


def _default_passthrough_decision(tool_name: str) -> str:
    if tool_name not in MUTATING_TOOLS:
        return "allow"
    override = os.environ.get("CATNEST_AGY_PASSTHROUGH")
    if override in ("allow", "ask", "deny_unless_prior_grant"):
        return override
    cfg_path = Path.home() / ".gemini" / "config" / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text("utf-8")) if cfg_path.is_file() else {}
        us = cfg.get("userSettings") or {}
        if (
            us.get("permissionPreset") == "AGENT_PERMISSION_PRESET_TURBO"
            or us.get("autoExecutionPolicy") == "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER"
        ):
            return "allow"
    except Exception:
        pass
    return "ask"


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        print(json.dumps({"decision": "ask"}))
        return 0

    event = str(payload.get("hookEventName") or "")
    try:
        if event == "PreInvocation":
            res = evaluate_pre_invocation(payload)
            steps = []
            if res.get("inject_system"):
                steps.append({"systemMessage": {"systemMessage": res["inject_system"]}})
            if res.get("inject_error"):
                steps.append({"errorMessage": {"userMessage": res["inject_error"]}})
            out: dict = {}
            if steps:
                out["injectSteps"] = steps
            if res.get("terminate"):
                out["terminationBehavior"] = "terminate"
            print(json.dumps(out, ensure_ascii=False))
            return 0

        tname = str((payload.get("toolCall") or {}).get("name") or "")
        res = evaluate_pre_tool(payload)
        act = res.get("action", "pass")
        if act == "deny":
            print(json.dumps({"decision": "deny", "reason": res.get("reason", "Blocked by catnest gate")}, ensure_ascii=False))
        elif act == "overwrite":
            print(json.dumps({
                "decision": _default_passthrough_decision(tname),
                "overwrite": res.get("overwrite") or {},
            }, ensure_ascii=False))
        else:
            print(json.dumps({"decision": _default_passthrough_decision(tname)}))
        return 0
    except Exception:
        tname = str((payload.get("toolCall") or {}).get("name") or "")
        out = {} if event == "PreInvocation" else {"decision": _default_passthrough_decision(tname)}
        print(json.dumps(out))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
