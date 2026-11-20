#!/usr/bin/env python3
"""catnest: zero-dependency self-maintaining workflow CLI (猫窝)."""

from __future__ import annotations

import argparse
from pathlib import Path

from catnest_lib import parse_canon_atoms
from catnest_lib.assemble import cmd_assemble
from catnest_lib.check import cmd_check
from catnest_lib.maintenance import cmd_friction, cmd_settle
from catnest_lib.recall import cmd_recall, cmd_touch

DIRS = ("canon", "probes", "open", "logs", "_state")


def find_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    cur = Path.cwd().resolve()
    for p in (cur, *cur.parents):
        if (p / "boot.md").is_file() and (p / "canon").is_dir():
            return p
    return cur


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve()
    for d in DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text("_state/\n__pycache__/\n*.pyc\n", encoding="utf-8")
    boot = root / "boot.md"
    if not boot.exists() or args.force:
        name = args.name or root.name
        boot.write_text(
            f"# {name} · 猫窝潜意识路由表（boot.md）\n\n"
            "> 猫是有名字的组装配方，不是割据实体；所有猫共享同一个窝（`canon/` + `open/` + `logs/`）。\n\n"
            "## 环境与仓库映射\n"
            f"- **猫窝根**：`{root}`\n\n"
            "## 猫配方（`catnest assemble <猫名>`）\n"
            "- `orange`（橘猫 · 全局前台与碰撞裁决）：`canon/*.md`, `open/*.md`\n\n"
            "## 当前活接力棒（滚动覆写，≤5 行）\n"
            "- **初始化**：等待写入首批 `[意图]`/`[事实]` 原子与 `probes/` 猫须探针。\n",
            encoding="utf-8",
        )
    print(f"initialized catnest: {root}")
    return 0


def cmd_status(root: Path, _args: argparse.Namespace) -> int:
    canon_files = sorted((root / "canon").glob("*.md")) if (root / "canon").is_dir() else []
    atoms = parse_canon_atoms(root)
    probes = sorted((root / "probes").glob("probe_*.py")) if (root / "probes").is_dir() else []
    opens = sorted((root / "open").glob("*.md")) if (root / "open").is_dir() else []
    logs = sorted((root / "logs").glob("*.md")) if (root / "logs").is_dir() else []
    suspect = root / "_state" / "suspect.md"
    suspect_state = "missing (run `catnest check`)"
    if suspect.is_file():
        lines = suspect.read_text("utf-8").splitlines()
        suspect_state = lines[0] if lines else "empty"
    print(f"nest:    {root}")
    print(f"canon:   {len(canon_files)} files, {len(atoms)} atoms")
    print(f"probes:  {len(probes)} whisker probes")
    print(f"open:    {len(opens)} active items")
    print(f"logs:    {len(logs)} append-only files")
    print(f"suspect: {suspect_state}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="catnest", description="Self-maintaining workflow CLI (猫窝)")
    p.add_argument("--root", help="Workflow root directory (auto-detected by default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="Initialize a workflow directory")
    s.add_argument("target", nargs="?", default=".")
    s.add_argument("--name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(handler=lambda _r, a: cmd_init(a))

    s = sub.add_parser("status", help="Show workflow health overview")
    s.set_defaults(handler=cmd_status)

    s = sub.add_parser("recall", help="BM25 + alias + ACT-R recall across canon/open/logs")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=6)
    s.add_argument("--no-logs", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(handler=cmd_recall)

    s = sub.add_parser("touch", help="Record an ACT-R touch on an atom or open/ item")
    s.add_argument("key")
    s.set_defaults(handler=cmd_touch)

    s = sub.add_parser("assemble", help="Resolve a boot.md context assembly recipe")
    s.add_argument("recipe", nargs="?")
    s.add_argument("--list", action="store_true")
    s.add_argument("--print", dest="print_bundle", action="store_true")
    s.add_argument("--no-touch", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(handler=cmd_assemble)

    s = sub.add_parser("check", help="Run behavior probes and refresh _state/suspect.md")
    s.add_argument("--all", action="store_true", help="Run all probes regardless of diff")
    s.add_argument("--mutate", action="store_true", help="Run probe mutation test to detect fake penetration")
    s.add_argument("--diff", help="Git diff range, e.g. HEAD~1..HEAD")
    s.add_argument("--repo", help="Target code repository path")
    s.add_argument("--install-hook", help="Install non-blocking post-commit hook in target git repo")
    s.set_defaults(handler=cmd_check)

    s = sub.add_parser("friction", help="Record runtime friction back into logs (and optionally open/)")
    s.add_argument("summary")
    s.add_argument("--kind", default="other", choices=("miss", "false-alarm", "bloat", "drift", "other"))
    s.add_argument("--atom", help="Related canon atom ID")
    s.add_argument("--context", help="Short context or pointer")
    s.add_argument("--open", action="store_true", help="Also promote into open/ for active resolution")
    s.add_argument("--meta", action="store_true", help="Route workflow friction back to catnest Project #0")
    s.set_defaults(handler=cmd_friction)

    s = sub.add_parser("settle", aliases=["purr"], help="Sink stale open/, emit passive retro signals, and blind-sample canon")
    s.add_argument("--days", type=int, default=14)
    s.add_argument("--sample", type=int, default=2)
    s.add_argument("--seed", type=int)
    s.add_argument("--repo", help="Target code repo for git revert signals")
    s.add_argument("--transcript", help="Optional session transcript.jsonl path for privacy-safe step pointers")
    s.add_argument("--apply", action="store_true", help="Actually move stale open/ items into logs/underwater-*")
    s.set_defaults(handler=cmd_settle)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(find_root(args.root), args)


if __name__ == "__main__":
    raise SystemExit(main())
