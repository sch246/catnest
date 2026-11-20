#!/usr/bin/env python3
# watches: canon/*.md, probes/*.py, logs/*.md
# atoms: D1
# summary: Enforce honest [意图] vs [事实] split, death conditions, and valid references (no fake penetration)

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catnest_lib import parse_canon_atoms  # noqa: E402

ASSERT_RE = re.compile(r"^\s*-\s*\*\*断言\*\*[：:]\s*\S+", re.M)
REF_RE = re.compile(r"`((?:probes|open|logs|canon)/[A-Za-z0-9_./-]+)(?:#[^`]+)?`")
SCOPED_FIELD_RE = re.compile(r"field:[A-Za-z0-9_.-]+@\d{4}-\d{2}-\d{2}\([^)]+\)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repo", default=".")
    root = Path(ap.parse_args().root)

    atoms = parse_canon_atoms(root)
    if not atoms:
        print("no canon atoms found under canon/")
        return 1

    seen_ids: set[str] = set()
    errors: list[str] = []
    for a in atoms:
        aid, nature, anc = a["id"], a["nature"], a["anchor_text"]
        if aid in seen_ids:
            errors.append(f"duplicate atom id [{aid}] in {a['path']}")
        seen_ids.add(aid)
        if nature not in ("意图", "事实"):
            errors.append(f"[{aid}] missing `- **性质**：`[意图]` or `[事实]``")
        if not ASSERT_RE.search(a["body"]):
            errors.append(f"[{aid}] missing `- **断言**：...`")
        if not a["has_anchor"]:
            errors.append(f"[{aid}] missing `- **锚点**：...`")
        if not a["has_death"]:
            errors.append(f"[{aid}] missing `- **死亡条件**：...`")
        if nature == "意图":
            if "probes/" in anc:
                errors.append(f"[{aid}] is [意图] but claims machine probe in anchor (fake penetration!)")
            if "logs/" not in anc:
                errors.append(f"[{aid}] is [意图] and must anchor to a `logs/` provenance entry")
        elif nature == "事实":
            if "probes/" not in anc and not SCOPED_FIELD_RE.search(anc):
                errors.append(f"[{aid}] is [事实] and must anchor to `probes/*.py` or scoped `field:target@date(watches)`")
        for ref in REF_RE.findall(a["body"]):
            if not (root / ref).exists():
                errors.append(f"[{aid}] broken reference `{ref}`")

    if errors:
        for e in errors:
            print(e)
        return 1
    n_int = sum(1 for a in atoms if a["nature"] == "意图")
    n_fct = sum(1 for a in atoms if a["nature"] == "事实")
    print(f"OK: {len(atoms)} atoms ({n_int} [意图] + {n_fct} [事实]), honest anchors & death conditions verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
