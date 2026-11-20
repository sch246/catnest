"""Shared atom parsing and ACT-R touch state for flow-engine."""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

ATOM_RE = re.compile(r"^###\s+\[([A-Za-z0-9_-]+)\]\s+(.+)$", re.M)
NATURE_RE = re.compile(r"^\s*-\s*\*\*性质\*\*[：:]\s*`?\[(意图|事实)\]`?", re.M)
ALIAS_RE = re.compile(r"^\s*-\s*\*\*别名\*\*[：:]\s*(.+)$", re.M)
ANCHOR_RE = re.compile(r"^\s*-\s*\*\*锚点\*\*[：:]\s*(.+)$", re.M)
DEATH_RE = re.compile(r"^\s*-\s*\*\*死亡条件\*\*[：:]\s*(.+)$", re.M)
USES_KEEP = 40


def state_dir(root: Path) -> Path:
    d = root / "_state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_uses(root: Path) -> dict[str, list[int]]:
    p = state_dir(root) / "uses.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def touch_key(root: Path, key: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    uses = load_uses(root)
    times = uses.setdefault(key, [])
    if times and now - times[-1] < 60:
        return
    times.append(round(now))
    del times[:-USES_KEEP]
    (state_dir(root) / "uses.json").write_text(
        json.dumps(uses, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def actr_score(uses: dict[str, list[int]], key: str, mtime: float, now: float | None = None) -> float:
    now = time.time() if now is None else now
    clock = now - now % 3600  # Hourly bucket preserves prompt prefix stability
    times = [t for t in uses.get(key, []) if t < clock] + [min(mtime, clock - 60)]
    return math.log(sum(max(clock - t, 60.0) ** -0.5 for t in times))


def parse_canon_atoms(root: Path) -> list[dict]:
    out: list[dict] = []
    cdir = root / "canon"
    if not cdir.is_dir():
        return out
    for f in sorted(cdir.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        text = f.read_text("utf-8")
        matches = list(ATOM_RE.finditer(text))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start() : end].strip()
            am = ALIAS_RE.search(body)
            aliases = [a.strip() for a in re.split(r"[,，、;；]", am.group(1)) if a.strip()] if am else []
            nm = NATURE_RE.search(body)
            anc = ANCHOR_RE.search(body)
            out.append({
                "kind": "canon",
                "id": m.group(1),
                "title": m.group(2).strip(),
                "nature": nm.group(1) if nm else None,
                "path": str(f.relative_to(root)),
                "body": body,
                "aliases": aliases,
                "anchor_text": anc.group(1).strip() if anc else "",
                "has_anchor": bool(anc),
                "has_death": bool(DEATH_RE.search(body)),
                "mtime": f.stat().st_mtime,
            })
    return out


def parse_doc_items(root: Path, folder: str) -> list[dict]:
    out: list[dict] = []
    d = root / folder
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.md")):
        text = f.read_text("utf-8")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")), f.stem)
        am = ALIAS_RE.search(text)
        aliases = [a.strip() for a in re.split(r"[,，、;；]", am.group(1)) if a.strip()] if am else []
        out.append({
            "kind": folder,
            "id": f"{folder}/{f.stem}",
            "title": title,
            "path": str(f.relative_to(root)),
            "body": text,
            "aliases": aliases,
            "mtime": f.stat().st_mtime,
        })
    return out
