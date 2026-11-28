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
DEFAULT_MAX_CONTEXT_LINES = 200
DEFAULT_MAX_CONTEXT_BYTES = 25_000
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


def _render_context_bundle(
    recipe: str,
    recipe_desc: str,
    role: str,
    sections: list[dict],
    deferred: list[dict],
    max_lines: int,
    max_bytes: int,
    forced: bool = False,
) -> str:
    file_sections = [section for section in sections if section["kind"] == "file"]
    budget_text = "forced full bundle" if forced else f"{max_lines} lines / {max_bytes} bytes"
    lines = [
        f"recipe: {recipe} ({recipe_desc}) | role: {role} | loaded files: {len(file_sections)} | "
        f"deferred sections: {len(deferred)} | startup budget: {budget_text}",
        "",
    ]
    for section in sections:
        lines.extend((section["heading"], section["text"].rstrip(), ""))
    if deferred:
        lines.append("按需读取（超出启动记忆预算）:")
        for section in deferred:
            lines.append(f"- {section['label']} ({section['line_count']}L)")
    return "\n".join(lines).rstrip() + "\n"


def _within_context_budget(text: str, max_lines: int, max_bytes: int) -> bool:
    return len(text.splitlines()) <= max_lines and len(text.encode("utf-8")) <= max_bytes


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
    out_files = [root / "boot.md"]
    if has_suspect:
        out_files.append(suspect)
    out_files.extend(files)

    collisions = recall_task_collisions(root, task, top=5) if task else []
    entries = [{"path": str(f.relative_to(root)), "lines": len(f.read_text("utf-8").splitlines())} for f in out_files if f.is_file()]
    files_only = getattr(args, "files_only", False)
    force_print = getattr(args, "print_bundle", False)
    max_lines = getattr(args, "max_lines", DEFAULT_MAX_CONTEXT_LINES)
    max_bytes = getattr(args, "max_bytes", DEFAULT_MAX_CONTEXT_BYTES)
    if files_only:
        total_lines = sum(e["lines"] for e in entries)
        print(f"recipe: {rec['name']} ({rec['desc']}) | role: {role} | {len(entries)} files, {total_lines} lines")
        for e in entries:
            print(f"  - {e['path']} ({e['lines']}L)")
        if missing:
            print(f"  ! missing patterns: {', '.join(missing)}")
        return 0

    candidates: list[dict] = []
    if role_card:
        candidates.append({
            "kind": "role",
            "label": f"[ROLE: {role}]",
            "heading": f"--- [ROLE: {role}] ---",
            "text": f"{role_card}\n{CANON_WRITE_HINT}",
            "line_count": len(role_card.splitlines()) + 1,
        })

    def add_file_section(f: Path) -> None:
        if f.is_file():
            rel = str(f.relative_to(root))
            content = f.read_text("utf-8")
            candidates.append({
                "kind": "file",
                "label": rel,
                "heading": f"--- {rel} ---",
                "text": content,
                "line_count": len(content.splitlines()),
            })

    if out_files:
        add_file_section(out_files[0])
    if task:
        collision_text = _format_task_collisions(task, collisions).strip()
        collision_lines = collision_text.splitlines()
        candidates.append({
            "kind": "task",
            "label": f"TASK COLLISION: {task}",
            "heading": collision_lines[0],
            "text": "\n".join(collision_lines[1:]),
            "line_count": len(collision_lines),
        })
    for f in out_files[1:]:
        add_file_section(f)
    if missing:
        missing_text = ", ".join(missing)
        candidates.append({
            "kind": "note",
            "label": "missing recipe paths",
            "heading": "--- MISSING RECIPE PATHS ---",
            "text": missing_text,
            "line_count": 1,
        })

    if force_print:
        selected = candidates
        deferred: list[dict] = []
    else:
        selected = []
        deferred = []
        required = [
            section for section in candidates
            if section["kind"] == "role"
            or (section["kind"] == "file" and section["label"] == "boot.md")
            or (has_suspect and section["kind"] == "file" and section["label"] == str(suspect.relative_to(root)))
        ]
        for section in candidates:
            if section not in required:
                continue
            trial = selected + [section]
            remaining = [item for item in candidates if item not in trial]
            bundle = _render_context_bundle(rec["name"], rec["desc"], role, trial, remaining, max_lines, max_bytes)
            if not _within_context_budget(bundle, max_lines, max_bytes):
                print(
                    f"error: required startup context exceeds the budget "
                    f"({max_lines} lines / {max_bytes} bytes); raise the budget or pass `--print`"
                )
                return 2
            selected = trial

        for section in candidates:
            if section in selected:
                continue
            trial = selected + [section]
            remaining = [item for item in candidates if item not in trial]
            bundle = _render_context_bundle(rec["name"], rec["desc"], role, trial, remaining, max_lines, max_bytes)
            if _within_context_budget(bundle, max_lines, max_bytes):
                selected = trial
            else:
                deferred.append(section)

    if not args.no_touch:
        loaded_paths = {
            section["label"]
            for section in selected
            if section["kind"] == "file"
        }
        for f in files:
            rel = str(f.relative_to(root))
            if rel not in loaded_paths:
                continue
            touch_key(root, rel[:-3] if rel.startswith(("open/", "logs/")) and rel.endswith(".md") else rel)
            if rel.startswith("canon/") and rel.endswith(".md"):
                for aid, _title in ATOM_RE.findall(f.read_text("utf-8")):
                    touch_key(root, aid)

    if args.json:
        deferred_paths = [section["label"] for section in deferred if section["kind"] == "file"]
        payload: dict = {
            "recipe": rec["name"],
            "role": role,
            "files": entries,
            "deferred": deferred_paths,
            "missing": missing,
            "suspect_attached": has_suspect,
        }
        if task is not None:
            payload["task_collisions"] = [{k: v for k, v in h.items() if k != "body"} for h in collisions]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    bundle = _render_context_bundle(
        rec["name"], rec["desc"], role, selected, deferred, max_lines, max_bytes, forced=force_print
    )
    print(bundle, end="")
    return 0
