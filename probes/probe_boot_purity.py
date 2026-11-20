#!/usr/bin/env python3
# watches: boot.md, canon/*.md, open/*.md, probes/*.py
# atoms: R1
# summary: Check boot.md stays a pure recipe router (no canon embedding, all cat recipes resolve)

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catnest_lib.assemble import parse_recipes, resolve_recipe  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repo", default=".")
    root = Path(ap.parse_args().root)

    boot = root / "boot.md"
    if not boot.is_file():
        print("boot.md missing")
        return 1

    text = boot.read_text("utf-8")
    lines = text.splitlines()
    errors: list[str] = []

    if len(lines) > 100:
        errors.append(f"boot.md exceeded 100L ({len(lines)}L); keep routing table thin and move prose to canon/ or logs/")
    if re.search(r"^###\s+\[[A-Za-z0-9_-]+\]", text, re.M):
        errors.append("boot.md embeds canon atom headings (`### [ID]`); keep canon exclusively in canon/")

    recipes = parse_recipes(root)
    if not recipes:
        errors.append("boot.md defines zero cat recipes under `## 猫配方`")
    for name in recipes:
        _rec, files, missing = resolve_recipe(root, name)
        if missing:
            errors.append(f"recipe `{name}` has unresolved patterns: {', '.join(missing)}")
        if not files:
            errors.append(f"recipe `{name}` resolves to 0 files")

    if errors:
        for e in errors:
            print(e)
        return 1
    print(f"OK: boot.md ({len(lines)}L), {len(recipes)} valid cat recipes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
