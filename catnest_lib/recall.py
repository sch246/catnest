"""Semantic/lexical recall (Chinese bigram BM25 + aliases + decay-exempt riverbanks & external evidence)."""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path

from . import actr_score, is_unclosed_tension, load_uses, parse_canon_atoms, parse_doc_items, state_dir, touch_key

EDGE_CHARS = set("的了是在我你他她它们这那就也都和与及或把被给到着过吗呢吧啊呀哦嗯么还又再很太个")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
WORD_RUN = re.compile(r"[a-z0-9_][a-z0-9_-]{1,}")
BACKTICK_RE = re.compile(r"`([^`]+)`")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
MAX_EVIDENCE_CHUNK_LINES = 36


def tokenize(text: str) -> Counter[str]:
    low = text.casefold()
    counts: Counter[str] = Counter()
    for w in WORD_RUN.findall(low):
        counts[w] += 1
    for run in CJK_RUN.findall(low):
        # Only drop bigrams where BOTH chars are pure particles; never rip '过'/'在'/'个' out of words like '过期'/'过程'
        if len(run) == 1:
            if run not in EDGE_CHARS:
                counts[run] += 1
            continue
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg[0] in EDGE_CHARS and bg[1] in EDGE_CHARS:
                continue
            counts[bg] += 1
    return counts


def parse_external_evidence_globs(root: Path) -> list[str]:
    boot = root / "boot.md"
    if not boot.is_file():
        return []
    patterns: list[str] = []
    in_section = False
    for raw in boot.read_text("utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_section = ("外部证据源" in line) or ("external evidence" in line.lower())
            continue
        if not in_section or not line.startswith("-"):
            continue
        rhs = line.lstrip("-").strip()
        cands = BACKTICK_RE.findall(rhs)
        if not cands:
            cleaned = re.sub(r"[（(][^）)]*[）)]", "", rhs)
            cands = [p.strip() for p in re.split(r"[,，]", cleaned) if p.strip()]
        for pat in cands:
            if not pat or pat.startswith(("/", "~")):
                continue
            # Strictly restrict whitelist to relative *.md text globs/paths
            if not pat.lower().endswith(".md"):
                continue
            norm_parts = Path(pat).parts
            leading_up = 0
            for pt in norm_parts:
                if pt == "..":
                    leading_up += 1
                else:
                    break
            if leading_up > 1 or ".." in norm_parts[leading_up:]:
                continue
            patterns.append(pat)
    return patterns


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _chunk_markdown_lines(lines: list[str], fallback_title: str) -> list[tuple[int, int, str, str]]:
    """Split markdown lines into `(start_line, end_line, title, body)` 1-indexed chunks."""
    sections: list[tuple[int, list[str], str]] = []
    cur_start = 1
    cur_title = fallback_title
    cur_buf: list[str] = []
    for idx, ln in enumerate(lines, 1):
        hm = HEADING_RE.match(ln.strip())
        if hm:
            if any(s.strip() for s in cur_buf):
                sections.append((cur_start, cur_buf, cur_title))
            cur_start = idx
            cur_title = hm.group(2).strip()
            cur_buf = [ln]
        else:
            if not cur_buf:
                cur_start = idx
            cur_buf.append(ln)
    if any(s.strip() for s in cur_buf):
        sections.append((cur_start, cur_buf, cur_title))

    chunks: list[tuple[int, int, str, str]] = []
    for s_start, s_lines, s_title in sections:
        if len(s_lines) <= MAX_EVIDENCE_CHUNK_LINES:
            end_offset = len(s_lines)
            while end_offset > 1 and not s_lines[end_offset - 1].strip():
                end_offset -= 1
            chunks.append((s_start, s_start + end_offset - 1, s_title, "\n".join(s_lines[:end_offset]).strip()))
            continue
        # Sub-split oversized section on blank lines
        p_start = s_start
        p_buf: list[str] = []
        for offset, ln in enumerate(s_lines):
            line_no = s_start + offset
            if not ln.strip() and len(p_buf) >= 12:
                if any(x.strip() for x in p_buf):
                    chunks.append((p_start, line_no - 1, s_title, "\n".join(p_buf).strip()))
                p_buf = []
                p_start = line_no + 1
                continue
            if not p_buf:
                p_start = line_no
            p_buf.append(ln)
            if len(p_buf) >= MAX_EVIDENCE_CHUNK_LINES:
                chunks.append((p_start, line_no, s_title, "\n".join(p_buf).strip()))
                p_buf = []
                p_start = line_no + 1
        if any(x.strip() for x in p_buf):
            end_no = p_start + len(p_buf) - 1
            while end_no > p_start and not p_buf[end_no - p_start].strip():
                end_no -= 1
            chunks.append((p_start, end_no, s_title, "\n".join(p_buf[: end_no - p_start + 1]).strip()))
    return chunks


def _compact_snippet(body: str, max_chars: int = 120) -> str:
    meaningful = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not meaningful:
        meaningful = [ln.strip() for ln in body.splitlines() if ln.strip()]
    joined = " ".join(meaningful[:2])
    return (joined[: max_chars - 1] + "…") if len(joined) > max_chars else joined


def parse_external_evidence_items(root: Path) -> list[dict]:
    root_res = root.resolve()
    patterns = parse_external_evidence_globs(root_res)
    if not patterns:
        return []
    allowed_top = root_res.parent.resolve()
    internal_dirs = {root_res / d for d in ("canon", "open", "logs", "_state", "probes")}
    seen_files: set[Path] = set()
    items: list[dict] = []

    for pat in patterns:
        allow_base = allowed_top if (pat.startswith("../") or root_res.name.startswith(".")) else root_res
        raw_matches = sorted(glob.glob(str(root_res / pat), recursive=True))
        for m in raw_matches:
            p = Path(m)
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            rp = p.resolve()
            if rp in seen_files or rp == (root_res / "boot.md").resolve():
                continue
            if not _is_within(rp, allow_base):
                continue
            if any(_is_within(rp, idir) for idir in internal_dirs):
                continue
            seen_files.add(rp)
            try:
                text = rp.read_text("utf-8")
            except OSError:
                continue
            rel_path = Path(os.path.relpath(rp, root_res)).as_posix()
            mtime = rp.stat().st_mtime
            for s_line, e_line, title, chunk_body in _chunk_markdown_lines(text.splitlines(), rp.stem):
                anchor = f"{rel_path}#L{s_line}-{e_line}"
                items.append({
                    "kind": "evidence",
                    "id": anchor,
                    "title": title,
                    "path": anchor,
                    "body": chunk_body,
                    "snippet": _compact_snippet(chunk_body),
                    "aliases": [],
                    "mtime": mtime,
                })
    return items


def is_decay_exempt(item: dict) -> bool:
    """Riverbank atoms (`[河岸]`) and in-place external evidence are exempt from ACT-R time decay / touch loops."""
    return item.get("nature") == "河岸" or item.get("kind") == "evidence"


def recall_items(
    root: Path,
    query: str,
    top: int = 6,
    include_logs: bool = True,
    include_evidence: bool = True,
) -> list[dict]:
    q_terms = set(tokenize(query).keys())
    items = parse_canon_atoms(root) + parse_doc_items(root, "open")
    if include_logs:
        items += parse_doc_items(root, "logs")
    if include_evidence:
        items += parse_external_evidence_items(root)
    if not q_terms or not items:
        return []

    doc_tfs: list[Counter[str]] = []
    df: Counter[str] = Counter()
    for it in items:
        tf = tokenize(it["title"] + "\n" + it["body"])
        for alias in it.get("aliases", []):
            for term, c in tokenize(alias).items():
                tf[term] += c * 3  # Learned aliases boost repair of past misses
        doc_tfs.append(tf)
        for term in tf:
            df[term] += 1

    n_docs = len(items)
    avg_len = sum(sum(tf.values()) for tf in doc_tfs) / n_docs or 1.0
    uses = load_uses(root)
    scored: list[dict] = []
    for it, tf in zip(items, doc_tfs):
        length = sum(tf.values()) or 1
        bm25 = 0.0
        matched: list[str] = []
        for term in q_terms:
            hits = tf.get(term, 0)
            if not hits:
                continue
            matched.append(term)
            idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            bm25 += idf * hits * 2.5 / (hits + 1.5 * (0.25 + 0.75 * length / avg_len))
        if bm25 <= 0:
            continue
        exempt = is_decay_exempt(it)
        if exempt:
            actr = 0.0
            total = bm25
        else:
            actr = actr_score(uses, it["id"], it["mtime"])
            freshness = max(min(actr + 8.0, 8.0), 0.0) / 8.0
            total = bm25 * (0.76 + 0.24 * freshness)
        snippet = it.get("snippet") or _compact_snippet(it["body"])
        scored.append({
            **it,
            "snippet": snippet,
            "decay_exempt": exempt,
            "bm25": round(bm25, 3),
            "actr": round(actr, 2),
            "score": round(total, 3),
            "matched": sorted(matched)[:6],
        })

    scored.sort(key=lambda x: (x["score"], 1 if x.get("decay_exempt") else 0), reverse=True)
    return scored[:top]


def recall_task_collisions(root: Path, task: str, top: int = 5) -> list[dict]:
    """Auto-collision for `assemble --task`: prioritize `[河岸]`, `[未闭合]` tensions, and `evidence` Top-5."""
    raw_hits = recall_items(root, task, top=max(top * 4, 20), include_logs=True, include_evidence=True)
    pri: list[dict] = []
    rest: list[dict] = []
    for h in raw_hits:
        is_pri = (
            h.get("nature") == "河岸"
            or h.get("kind") == "evidence"
            or (h.get("kind") == "open" and is_unclosed_tension(h.get("body", ""), h.get("title", "")))
        )
        (pri if is_pri else rest).append(h)
    picked = (pri + rest)[:top]
    log_recall(root, task, picked)
    return picked


def log_recall(root: Path, query: str, hits: list[dict]) -> None:
    rec = {
        "ts": round(time.time()),
        "query": query,
        "hits": [h["id"] for h in hits],
        "top_score": hits[0]["score"] if hits else 0.0,
    }
    with (state_dir(root) / "recall.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_recall(root: Path, args: argparse.Namespace) -> int:
    hits = recall_items(root, args.query, top=args.top, include_logs=not args.no_logs)
    log_recall(root, args.query, hits)
    if args.json:
        print(json.dumps([{k: v for k, v in h.items() if k != "body"} for h in hits], ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print(f"no hits for: {args.query}")
        return 0
    for i, h in enumerate(hits, 1):
        tag = h.get("nature") or h["kind"]
        actr_str = "exempt" if h.get("decay_exempt") else str(h["actr"])
        print(f"{i}. [{tag}] {h['id']} — {h['title']}  (score={h['score']}, bm25={h['bm25']}, actr={actr_str})")
        print(f"   path: {h['path']} | matched: {', '.join(h['matched'])}")
        if h["kind"] == "evidence" and h.get("snippet"):
            print(f"   > {h['snippet']}")
    return 0


def cmd_touch(root: Path, args: argparse.Namespace) -> int:
    key = args.key
    touch_key(root, key)
    cand = root / key if key.endswith(".md") else root / f"{key}.md"
    if cand.is_file() and cand.parent.name == "open":
        text = cand.read_text("utf-8")
        today = date.today().isoformat()
        new_text = re.sub(r"^last_touched:\s*.*$", f"last_touched: {today}", text, count=1, flags=re.M)
        if new_text != text:
            cand.write_text(new_text, encoding="utf-8")
    print(f"touched: {key}")
    return 0
