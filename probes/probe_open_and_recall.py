#!/usr/bin/env python3
# watches: catnest_lib/recall.py, catnest_lib/maintenance.py
# atoms: D3
# mutate: catnest_lib/recall.py::bg[0] in EDGE_CHARS and bg[1] in EDGE_CHARS=>bg[0] in EDGE_CHARS or bg[1] in EDGE_CHARS
# summary: Non-self-certifying recall regression (compound CJK words) + real adoption-rate guard

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catnest_lib.maintenance import recall_adoption_stats  # noqa: E402
from catnest_lib.recall import tokenize  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repo", default=".")
    root = Path(ap.parse_args().root)

    errors: list[str] = []

    # 1. Regression anchor from real 2026-11-20 friction: particles inside compound words must survive
    toks = tokenize("防文档过期与过程折叠")
    for expected in ("过期", "过程", "文档"):
        if expected not in toks:
            errors.append(f"tokenizer stripped compound bigram `{expected}` from tokens: {sorted(toks)}")

    # 2. D3 real death condition: once >=20 recalls exist, actual adoption rate must stay >= 40%
    st = recall_adoption_stats(root)
    if st["total"] >= 20 and st["rate"] is not None and st["rate"] < 0.40:
        errors.append(
            f"D3 death condition triggered: recall adoption {st['rate']:.0%} < 40% "
            f"over {st['total']} queries (logged misses={st['miss_frictions']})"
        )

    if errors:
        for e in errors:
            print(e)
        return 1
    rate_str = f"{st['rate']*100:.0f}%" if st["rate"] is not None else "N/A"
    print(f"OK: compound CJK tokenizer intact; adoption={rate_str} ({st['adopted']}/{st['total']}, misses={st['miss_frictions']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
