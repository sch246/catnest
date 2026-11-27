"""Shared atom parsing, single-source role policy, and ACT-R touch state for catnest."""

from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

ATOM_RE = re.compile(r"^###\s+\[([A-Za-z0-9_-]+)\]\s+(.+)$", re.M)
NATURE_RE = re.compile(r"^\s*-\s*\*\*性质\*\*[：:]\s*`?\[(河岸|裁决|事实|意图)\]`?", re.M)
ALIAS_RE = re.compile(r"^\s*-\s*\*\*别名\*\*[：:]\s*(.+)$", re.M)
ANCHOR_RE = re.compile(r"^\s*-\s*\*\*锚点\*\*[：:]\s*(.+)$", re.M)
EVIDENCE_RE = re.compile(r"^\s*(?:-\s*)?(?:\*\*证据\*\*|证据)\s*[：:]\s*(.+)$", re.M)
ORIGIN_RE = re.compile(r"^\s*(?:-\s*)?(?:\*\*来由\*\*|来由)\s*[：:]\s*(.+)$", re.M)
COLLISION_RE = re.compile(r"^\s*(?:-\s*)?(?:\*\*碰撞\*\*|碰撞)\s*[：:]\s*(.+)$", re.M)
DEATH_RE = re.compile(r"^\s*-\s*\*\*死亡条件\*\*[：:]\s*(.+)$", re.M)
MATERIALIZED_RE = re.compile(r"^\s*(?:-\s*)?(?:\*\*物化\*\*|物化)\s*[：:]\s*(.+)$", re.M)
PLACEHOLDER_VAL_RE = re.compile(r"^(?:无|暂无|待补|待定|none|n/a|tbd|-+)$", re.I)


def extract_materialized_paths(mat_text: str) -> list[str]:
    ticks = re.findall(r"`([^`]+)`", mat_text)
    tokens = ticks if ticks else re.split(r"[,，;；\s]+", mat_text)
    out: list[str] = []
    for tok in tokens:
        p = tok.split("#", 1)[0].strip().strip("`'\"")
        if p and p not in (".", "./", "/") and not PLACEHOLDER_VAL_RE.match(p):
            out.append(p)
    return out
UNCLOSED_RE = re.compile(r"(?:\[未闭合\]|\[UNCLOSED\]|(?:^|\n|\*\*)\s*张力\s*(?:\*\*)?\s*[：:])", re.I)
USES_KEEP = 40


def engine_root() -> Path:
    return Path(os.environ.get("CATNEST_HOME") or Path(__file__).resolve().parent.parent).expanduser().resolve()


def is_unclosed_tension(text: str, title: str = "") -> bool:
    combined = f"{title}\n{text}" if title else text
    return bool(UNCLOSED_RE.search(combined))


def load_roles_config(root: Path | None = None) -> dict:
    base_file = engine_root() / "roles.json"
    cfg: dict = json.loads(base_file.read_text("utf-8")) if base_file.is_file() else {"defaults": {}, "roles": {}}
    if root is not None:
        custom = root.resolve() / "roles.json"
        if custom.is_file() and custom != base_file.resolve():
            try:
                ov = json.loads(custom.read_text("utf-8"))
                cfg.setdefault("defaults", {}).update(ov.get("defaults") or {})
                for rname, rspec in (ov.get("roles") or {}).items():
                    if rname in cfg.setdefault("roles", {}):
                        cfg["roles"][rname] = {**cfg["roles"][rname], **rspec}
                    else:
                        cfg["roles"][rname] = rspec
            except (OSError, ValueError):
                pass
    return cfg


def render_role_card_from_config(role: str, cfg: dict) -> str:
    rspec = (cfg.get("roles") or {}).get(role)
    if not rspec:
        return ""
    lines = []
    for b in rspec.get("bullets") or []:
        lines.append(f"- {b.format_map(rspec)}")
    return "\n".join(lines)


def render_roles_markdown(cfg: dict) -> str:
    lines = ["# catnest 角色行动契约卡（由 `roles.json` 单一真源生成，随 `assemble --role` 注入）", ""]
    for role in ("main", "deputy", "worker", "tentacle"):
        if role not in (cfg.get("roles") or {}):
            continue
        lines.append(f"## {role}")
        lines.append(render_role_card_from_config(role, cfg))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
            ev = EVIDENCE_RE.search(body)
            orig = ORIGIN_RE.search(body)
            col = COLLISION_RE.search(body)
            dm = DEATH_RE.search(body)
            mat = MATERIALIZED_RE.search(body)
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
                "evidence_text": ev.group(1).strip() if ev else "",
                "has_evidence": bool(ev),
                "origin_text": orig.group(1).strip() if orig else "",
                "has_origin": bool(orig),
                "collision_text": col.group(1).strip() if col else "",
                "has_collision": bool(col),
                "death_text": dm.group(1).strip() if dm else "",
                "has_death": bool(dm),
                "materialized_text": mat.group(1).strip() if mat else "",
                "has_materialized": bool(mat),
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
