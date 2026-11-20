"""Semantic/lexical recall (Chinese bigram BM25 + aliases + ACT-R) and touch."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path

from . import actr_score, load_uses, parse_canon_atoms, parse_doc_items, state_dir, touch_key

EDGE_CHARS = set("的了是在我你他她它们这那就也都和与及或把被给到着过吗呢吧啊呀哦嗯么还又再很太个")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
WORD_RUN = re.compile(r"[a-z0-9_][a-z0-9_-]{1,}")


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


def recall_items(root: Path, query: str, top: int = 6, include_logs: bool = True) -> list[dict]:
    q_terms = set(tokenize(query).keys())
    items = parse_canon_atoms(root) + parse_doc_items(root, "open")
    if include_logs:
        items += parse_doc_items(root, "logs")
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
        actr = actr_score(uses, it["id"], it["mtime"])
        # Mild ACT-R lift (keeps relevance primary while surfacing recently active islands)
        total = bm25 * (1.0 + 0.06 * max(min(actr + 8.0, 8.0), 0.0))
        scored.append({**it, "bm25": round(bm25, 3), "actr": round(actr, 2), "score": round(total, 3), "matched": sorted(matched)[:6]})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top]


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
        print(f"{i}. [{h['kind']}] {h['id']} — {h['title']}  (score={h['score']}, bm25={h['bm25']}, actr={h['actr']})")
        print(f"   path: {h['path']} | matched: {', '.join(h['matched'])}")
    return 0


def cmd_touch(root: Path, args: argparse.Namespace) -> int:
    key = args.key
    touch_key(root, key)
    # If touching an open/ markdown file, also refresh its frontmatter last_touched
    cand = root / key if key.endswith(".md") else root / f"{key}.md"
    if cand.is_file() and cand.parent.name == "open":
        text = cand.read_text("utf-8")
        today = date.today().isoformat()
        new_text = re.sub(r"^last_touched:\s*.*$", f"last_touched: {today}", text, count=1, flags=re.M)
        if new_text != text:
            cand.write_text(new_text, encoding="utf-8")
    print(f"touched: {key}")
    return 0
