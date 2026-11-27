"""Context assembly recipes parsed from boot.md (cats = assembly recipes, not entities)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import ATOM_RE, engine_root, is_unclosed_tension, load_roles_config, render_role_card_from_config, touch_key
from .recall import recall_task_collisions

RECIPE_LINE_RE = re.compile(r"^\s*-\s*`([A-Za-z0-9_-]+)`(?:\s*[（(]([^）)]*)[）)])?[：:]\s*(.+)$")
BACKTICK_RE = re.compile(r"`([^`]+)`")
DEFAULT_MAX_PRINT_LINES = 450
CANON_WRITE_HINT = "- 写 canon 必带来由与可观察死法；能物化成代码/探针即撤出条文"


def load_role_card(role: str, root: Path | None = None) -> str:
    if not role or role == "none":
        return ""
    cfg = load_roles_config(root)
    rendered = render_role_card_from_config(role, cfg)
    if rendered:
        return rendered
    cands = ([root / "templates" / "roles.md"] if root is not None else []) + [engine_root() / "templates" / "roles.md"]
    text = next((p.read_text("utf-8") for p in cands if p.is_file()), "")
    if not text:
        return ""
    m = re.search(rf"^##\s+{re.escape(role)}\s*\n(.*?)(?=^##\s+|\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def parse_recipes(root: Path) -> dict[str, dict]:
    boot = root / "boot.md"
    if not boot.is_file():
        return {}
    recipes: dict[str, dict] = {}
    in_section = False
    for line in boot.read_text("utf-8").splitlines():
        if line.startswith("## "):
            in_section = any(k in line.lower() for k in ("猫配方", "组装配方", "recipes"))
            continue
        if not in_section:
            continue
        m = RECIPE_LINE_RE.match(line)
        if not m:
            continue
        name, desc, rhs = m.group(1), (m.group(2) or "").strip(), m.group(3)
        patterns = BACKTICK_RE.findall(rhs)
        if not patterns:
            patterns = [p.strip() for p in re.split(r"[,，]", rhs) if p.strip()]
        recipes[name] = {"name": name, "desc": desc, "patterns": patterns}
    return recipes


def resolve_recipe(root: Path, name: str) -> tuple[dict, list[Path], list[str]]:
    recipes = parse_recipes(root)
    if name not in recipes:
        raise KeyError(f"unknown recipe '{name}' (available: {', '.join(sorted(recipes)) or 'none'})")
    rec = recipes[name]
    files: list[Path] = []
    seen: set[Path] = set()
    missing: list[str] = []
    for pat in rec["patterns"]:
        matched = sorted(root.glob(pat)) if any(c in pat for c in "*?[") else ([root / pat] if (root / pat).is_file() else [])
        if not matched:
            missing.append(pat)
        for p in matched:
            rp = p.resolve()
            if p.is_file() and rp not in seen:
                seen.add(rp)
                files.append(p)
    return rec, files, missing


def _format_task_collisions(task: str, hits: list[dict]) -> str:
    lines = [f"\n--- [TASK COLLISION: {task}] ---"]
    if not hits:
        lines.append("(no lexical hits; check aliases or broaden query)")
        return "\n".join(lines)
    for i, h in enumerate(hits, 1):
        if h.get("kind") == "open" and is_unclosed_tension(h.get("body", ""), h.get("title", "")):
            tag = "未闭合"
        else:
            tag = h.get("nature") or h["kind"]
        lines.append(f"{i}. [{tag}] {h['id']} — {h['title']} ({h['path']}, score={h['score']})")
        if h.get("snippet"):
            lines.append(f"   > {h['snippet']}")
    return "\n".join(lines)


def cmd_assemble(root: Path, args: argparse.Namespace) -> int:
    role = getattr(args, "role", "main") or "main"
    task = getattr(args, "task", None)
    role_card = load_role_card(role, root)
    recipes = parse_recipes(root)
    if args.list or not args.recipe:
        if not args.list and role in ("deputy", "worker", "tentacle") and role_card and not args.json:
            print(f"--- [ROLE: {role}] ---\n{role_card}\n{CANON_WRITE_HINT}")
            if task:
                print(_format_task_collisions(task, recall_task_collisions(root, task, top=5)))
            return 0
        if args.json:
            print(json.dumps(recipes, ensure_ascii=False, indent=2))
            return 0
        for r in recipes.values():
            print(f"- {r['name']} ({r['desc']}): {', '.join(r['patterns'])}")
        return 0

    try:
        rec, files, missing = resolve_recipe(root, args.recipe)
    except KeyError as e:
        print(f"error: {e}")
        return 2

    suspect = root / "_state" / "suspect.md"
    suspect_txt = suspect.read_text("utf-8") if suspect.is_file() else ""
    has_suspect = "## FAIL" in suspect_txt or "## EXPIRED" in suspect_txt
    out_files = [root / "boot.md", *files]
    if has_suspect:
        out_files.append(suspect)

    if not args.no_touch:
        for f in files:
            rel = str(f.relative_to(root))
            touch_key(root, rel[:-3] if rel.startswith(("open/", "logs/")) and rel.endswith(".md") else rel)
            if rel.startswith("canon/") and rel.endswith(".md"):
                for aid, _title in ATOM_RE.findall(f.read_text("utf-8")):
                    touch_key(root, aid)

    collisions = recall_task_collisions(root, task, top=5) if task else []
    entries = [{"path": str(f.relative_to(root)), "lines": len(f.read_text("utf-8").splitlines())} for f in out_files if f.is_file()]
    if args.json:
        payload: dict = {
            "recipe": rec["name"],
            "role": role,
            "files": entries,
            "missing": missing,
            "suspect_attached": has_suspect,
        }
        if task is not None:
            payload["task_collisions"] = [{k: v for k, v in h.items() if k != "body"} for h in collisions]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    total_lines = sum(e["lines"] for e in entries)
    print(f"recipe: {rec['name']} ({rec['desc']}) | role: {role} | {len(entries)} files, {total_lines} lines")
    for e in entries:
        print(f"  - {e['path']} ({e['lines']}L)")
    if missing:
        print(f"  ! missing patterns: {', '.join(missing)}")

    files_only = getattr(args, "files_only", False)
    force_print = getattr(args, "print_bundle", False)
    max_lines = getattr(args, "max_lines", DEFAULT_MAX_PRINT_LINES)
    if role_card and not files_only:
        print(f"\n--- [ROLE: {role}] ---\n{role_card}\n{CANON_WRITE_HINT}")
    if files_only:
        return 0
    if not force_print and total_lines > max_lines:
        print(f"\n! bundle has {total_lines}L (> {max_lines}L); slim recipe or pass `--print` to force full output")
        if task:
            print(_format_task_collisions(task, collisions))
        return 0

    print("\n" + "=" * 60)
    for f in out_files:
        if f.is_file():
            print(f"\n--- {f.relative_to(root)} ---\n")
            print(f.read_text("utf-8").rstrip())
    if task:
        print(_format_task_collisions(task, collisions))
    return 0
