#!/usr/bin/env python3
# kind: HYGIENE
# watches: canon/*.md, probes/*.py, logs/*.md
# atoms: D1
# mutate: canon/01-tensions.md::- **来由**：=>- **碰撞**：
# mutate: canon/01-tensions.md::目标项目属于完全确定的零漂移流水线。=>用户 Supersedes
# summary: Enforce [河岸]/[裁决]/[事实] origin & evidence anchors, observable death conditions, and optional 物化: withdrawal hints

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catnest_lib import MATERIALIZED_RE, extract_materialized_paths, parse_canon_atoms  # noqa: E402

ASSERT_RE = re.compile(r"^\s*-\s*\*\*断言\*\*[：:]\s*\S+", re.M)
REF_RE = re.compile(r"`((?:probes|open|logs|canon|hooks|catnest_lib)/[A-Za-z0-9_./-]+)(?:#[^`]+)?`")
SCOPED_FIELD_RE = re.compile(r"field:[A-Za-z0-9_.-]+@\d{4}-\d{2}-\d{2}\([^)]+\)")
EVIDENCE_ANCHOR_RE = re.compile(
    r"(?:#L\d+(?:-(?:L)?\d+)?|#R\d+|probes/probe_\S+\.py|field:[A-Za-z0-9_.-]+@\d{4}-\d{2}-\d{2}|\S+\.md\b|「[^」]{2,}」|“[^”]{2,}”|\"[^\"]{3,}\")"
)
ORIGIN_ANCHOR_RE = re.compile(
    r"(?:#L\d+(?:-(?:L)?\d+)?|#R\d+|\b(?:logs|open|canon|probes)/\S+|\S+\.(?:md|py|json|sh|ts|js|rs|go)\b|「[^」]{2,}」|“[^”]{2,}”|\"[^\"]{3,}\")"
)
PLACEHOLDER_RE = re.compile(r"^(?:无|暂无|待补|待定|none|n/a|tbd|-+)$", re.I)
TAUTOLOGICAL_DEATH_RE = re.compile(
    r"^(?:当)?(?:"
    r"(?:用户|人工|作者|团队)?(?:以新原话|明确|显式|口头|新指令|指令)?\s*(?:supersedes?|推翻|否决|废除|取消|修改|改主意|废止)(?:本条|该条|此条|此规则)?|"
    r"(?:本条|该条|此条|此规则|条文|方案)?(?:被(?:新规则|新条文|新方案|新裁决|上位替代|其他方案)?(?:取代|替代|覆盖|废弃|推翻|删除|supersedes?)|不再(?:适用|需要|成立|有效)|过期|失效)"
    r")(?:时|后)?(?:失效|作废)?$",
    re.I,
)


def is_vague_death(text: str) -> bool:
    clauses = re.split(r"[，,；;。]+|(?:\s+)(?:或|或者|or)(?:\s+)", text)
    for raw in clauses:
        cl = re.sub(r"^(?:或|或者|or)\s*", "", raw.strip(), flags=re.I)
        cl_clean = re.sub(r"[`*_\"'「」“”()（）\s.。！!？?-]", "", cl)
        if not cl_clean or len(cl_clean) < 3 or PLACEHOLDER_RE.match(cl_clean):
            continue
        cl_norm = re.sub(r"[`*_\"'「」“”]", "", cl).strip().rstrip("。！!.")
        if TAUTOLOGICAL_DEATH_RE.match(cl_norm):
            continue
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    root = Path(args.root)
    repo = Path(args.repo)

    atoms = parse_canon_atoms(root)
    if not atoms:
        print("no canon atoms found under canon/")
        return 1

    seen_ids: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []
    for a in atoms:
        aid, nature = a["id"], a["nature"]
        anc, ev, orig = a["anchor_text"], a["evidence_text"], a.get("origin_text", "")
        if aid in seen_ids:
            errors.append(f"duplicate atom id [{aid}] in {a['path']}")
        seen_ids.add(aid)
        if not ASSERT_RE.search(a["body"]):
            errors.append(f"[{aid}] missing `- **断言**：...`")
        if not a["has_death"]:
            errors.append(f"[{aid}] missing `- **死亡条件**：...`")
        elif is_vague_death(a.get("death_text", "")):
            errors.append(
                f"[{aid}] tautological or vague `死亡条件` (`{a.get('death_text', '')}`); "
                "specify an observable reality change or code materialization"
            )

        if nature == "意图":
            errors.append(
                f"[{aid}] legacy `[意图]` atom is rejected (exempt privilege removed); "
                "migrate to `[河岸]` (with `证据:`) or `[裁决]` (with `来由:`)"
            )
        elif nature == "河岸":
            if not a["has_evidence"] or PLACEHOLDER_RE.match(ev) or not EVIDENCE_ANCHOR_RE.search(ev):
                errors.append(
                    f"[{aid}] is `[河岸]` and must include `证据:` pointing to `path#Lx-y` line numbers or empirical anchor"
                )
        elif nature == "裁决":
            dec_src = orig if a.get("has_origin") else ev
            if (not a.get("has_origin") and not a["has_evidence"]) or PLACEHOLDER_RE.match(dec_src) or not ORIGIN_ANCHOR_RE.search(dec_src):
                errors.append(
                    f"[{aid}] is `[裁决]` and must include `来由:` (or `证据:`) citing user quote `「…」`, `logs/...`, or `path#Lx-y`"
                )
        elif nature == "事实":
            combined_anc = f"{anc} {ev}".strip()
            if "probes/" not in combined_anc and not SCOPED_FIELD_RE.search(combined_anc):
                errors.append(f"[{aid}] is `[事实]` and must anchor to `probes/*.py` or scoped `field:target@date(watches)`")
        else:
            errors.append(f"[{aid}] missing or invalid `- **性质**：` (must be `[河岸]`, `[裁决]`, or probe-backed `[事实]`)")

        if a.get("has_materialized"):
            for mp in extract_materialized_paths(a.get("materialized_text", "")):
                if (root / mp).exists() or (repo / mp).exists():
                    warnings.append(f"WARN [{aid}] `物化: {mp}` 已存在：已物化为代码/探针，可考虑撤出文本条文")

        body_without_mat = MATERIALIZED_RE.sub("", a["body"])
        for ref in REF_RE.findall(body_without_mat):
            if not (root / ref).exists() and not (repo / ref).exists():
                errors.append(f"[{aid}] broken reference `{ref}`")

    if errors:
        for e in errors:
            print(e)
        return 1
    for w in warnings:
        print(w)
    n_rb = sum(1 for a in atoms if a["nature"] == "河岸")
    n_rd = sum(1 for a in atoms if a["nature"] == "裁决")
    n_fc = sum(1 for a in atoms if a["nature"] == "事实")
    print(f"OK: {len(atoms)} atoms ({n_rb} [河岸] + {n_rd} [裁决] + {n_fc} [事实]), origin/evidence/death anchors verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
