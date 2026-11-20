"""Context assembly recipes parsed from boot.md (cats = assembly recipes, not entities)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import ATOM_RE, touch_key

RECIPE_LINE_RE = re.compile(r"^\s*-\s*`([A-Za-z0-9_-]+)`(?:\s*[（(]([^）)]*)[）)])?[：:]\s*(.+)$")
BACKTICK_RE = re.compile(r"`([^`]+)`")


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


def cmd_assemble(root: Path, args: argparse.Namespace) -> int:
    recipes = parse_recipes(root)
    if args.list or not args.recipe:
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

    entries = [{"path": str(f.relative_to(root)), "lines": len(f.read_text("utf-8").splitlines())} for f in out_files if f.is_file()]
    if args.json:
        print(json.dumps({"recipe": rec["name"], "files": entries, "missing": missing, "suspect_attached": has_suspect}, ensure_ascii=False, indent=2))
        return 0

    total_lines = sum(e["lines"] for e in entries)
    print(f"recipe: {rec['name']} ({rec['desc']}) | {len(entries)} files, {total_lines} lines")
    for e in entries:
        print(f"  - {e['path']} ({e['lines']}L)")
    if missing:
        print(f"  ! missing patterns: {', '.join(missing)}")
    if args.print_bundle:
        print("\n" + "=" * 60)
        for f in out_files:
            if f.is_file():
                print(f"\n--- {f.relative_to(root)} ---\n")
                print(f.read_text("utf-8").rstrip())
    return 0
