"""Machine reflex: run matching behavior probes (split HYGIENE vs ANCHORED) and expire field anchors -> _state/suspect.md."""

from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import extract_materialized_paths, parse_canon_atoms, state_dir

META_RE = re.compile(r"^#\s*(watches|atoms|summary|mutate|kind|category|tier)\s*:\s*(.+)$", re.M)
# Optional scoped watches: field:robot-a@2026-11-20(src/motion/*,config/bt.json)
FIELD_RE = re.compile(r"field:([A-Za-z0-9_.-]+)@(\d{4}-\d{2}-\d{2})(?:\(([^)]+)\))?")


def parse_probe_meta(path: Path) -> dict:
    head = "\n".join(path.read_text("utf-8").splitlines()[:25])
    meta = {"path": path, "watches": ["*"], "atoms": [], "summary": path.stem, "mutates": [], "kind": "HYGIENE"}
    for m in META_RE.finditer(head):
        k, v = m.group(1), m.group(2).strip()
        if k == "watches":
            meta["watches"] = [w.strip() for w in re.split(r"[,，]", v) if w.strip()]
        elif k == "atoms":
            meta["atoms"] = [a.strip() for a in re.split(r"[,，]", v) if a.strip()]
        elif k == "mutate":
            meta["mutates"].append(v)
        elif k in ("kind", "category", "tier"):
            meta["kind"] = "ANCHORED" if v.upper() == "ANCHORED" else "HYGIENE"
        else:
            meta["summary"] = v
    return meta


def git_changed_files(repo: Path, diff_ref: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", diff_ref],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def git_changed_since(repo: Path, since_date: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "log", f"--since={since_date} 23:59:59", "--name-only", "--pretty=format:"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return []
    return sorted({ln.strip() for ln in proc.stdout.splitlines() if ln.strip()})


def matches_any(changed: list[str], watches: list[str]) -> bool:
    if "*" in watches:
        return True
    return any(fnmatch.fnmatch(c, w) or c.startswith(w.rstrip("*")) for c in changed for w in watches)


def run_probe(root: Path, repo: Path, meta: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(meta["path"]), "--root", str(root), "--repo", str(repo)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    warnings = [ln.strip() for ln in out.splitlines() if ln.lstrip().startswith("WARN")]
    return {
        "name": meta["path"].name,
        "kind": meta.get("kind", "HYGIENE"),
        "summary": meta["summary"],
        "atoms": meta["atoms"],
        "ok": proc.returncode == 0,
        "warnings": warnings,
        "output": "\n".join(out.splitlines()[:12]),
    }


def run_mutation_checks(root: Path, metas: list[dict]) -> list[str]:
    """Verify every probe actually FAILS when its target contract is broken (# mutate: file::old=>new or empty nest)."""
    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "empty"
        for d in ("canon", "probes", "open", "logs", "_state"):
            (empty / d).mkdir(parents=True)
        for m in metas:
            if not m["mutates"]:
                r = run_probe(empty, empty, m)
                if r["ok"]:
                    survivors.append(f"`{m['path'].name}` survived empty-nest check (always PASS = fake penetration)")
                continue
            for spec in m["mutates"]:
                rel, sep, rest = spec.partition("::")
                old, sep2, new = rest.partition("=>")
                if not sep or not sep2:
                    survivors.append(f"`{m['path'].name}` invalid `# mutate:` syntax: `{spec}`")
                    continue
                clone = Path(td) / f"mut_{m['path'].stem}_{len(survivors)}"
                shutil.copytree(root, clone, ignore=shutil.ignore_patterns(".git", "_state", "__pycache__"))
                target = clone / rel.strip()
                txt = target.read_text("utf-8") if target.is_file() else ""
                if old not in txt:
                    survivors.append(f"`{m['path'].name}` mutate target `{old}` not found in `{rel.strip()}`")
                    continue
                target.write_text(txt.replace(old, new, 1), encoding="utf-8")
                cloned_meta = {**m, "path": clone / "probes" / m["path"].name}
                if not cloned_meta["path"].is_file():
                    cloned_meta["path"] = m["path"]
                r = run_probe(clone, clone, cloned_meta)
                if r["ok"]:
                    survivors.append(f"`{m['path'].name}` survived mutation `{rel.strip()}::{old}=>{new}` (fake penetration!)")
                shutil.rmtree(clone, ignore_errors=True)
    return survivors


def cmd_check(root: Path, args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve() if args.repo else root
    if args.install_hook:
        return _install_hook(root, Path(args.install_hook).expanduser().resolve())

    probes_dir = root / "probes"
    metas = [parse_probe_meta(p) for p in sorted(probes_dir.glob("probe_*.py"))] if probes_dir.is_dir() else []
    changed: list[str] | None = None
    if args.diff and not args.all and not args.mutate:
        changed = git_changed_files(repo, args.diff)
        metas = [m for m in metas if matches_any(changed, m["watches"])]

    results = [run_probe(root, repo, m) for m in metas]
    fake_pen = run_mutation_checks(root, metas) if getattr(args, "mutate", False) else []
    expired: list[dict] = []
    if (repo / ".git").exists():
        for atom in parse_canon_atoms(root):
            scan_text = atom["body"]
            for fm in FIELD_RE.finditer(scan_text):
                target, dt, scope = fm.group(1), fm.group(2), fm.group(3)
                watches = [w.strip() for w in re.split(r"[,，]", scope) if w.strip()] if scope else []
                if not watches:
                    continue
                cfiles = [c for c in git_changed_since(repo, dt) if matches_any([c], watches)]
                if cfiles:
                    expired.append({"id": atom["id"], "target": target, "date": dt, "changed_count": len(cfiles)})

    failed = [r for r in results if not r["ok"]]
    hyg = [r for r in results if r["kind"] == "HYGIENE"]
    anc = [r for r in results if r["kind"] == "ANCHORED"]
    hyg_pass = sum(1 for r in hyg if r["ok"])
    anc_pass = sum(1 for r in anc if r["ok"])
    tier_summary = f"HYGIENE: {hyg_pass}/{len(hyg)} | ANCHORED: {anc_pass}/{len(anc)}"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bad = bool(failed or expired or fake_pen)
    status = "CLEAN" if not bad else f"ALERT ({len(failed)} FAIL, {len(expired)} EXPIRED, {len(fake_pen)} FAKE_PEN)"
    lines = [
        f"# _state/suspect.md — {status}",
        f"- generated: {now_str} | probes run: {len(results)} ({tier_summary}) | diff: {args.diff or ('MUTATE' if getattr(args, 'mutate', False) else 'ALL')}",
        "",
    ]
    if failed:
        lines.append("## FAIL 探针（需修复或更新断言）")
        for r in failed:
            lines.append(f"- **FAIL** [{r['kind']}] `{r['name']}` ({', '.join(r['atoms']) or '-'}): {r['summary']}")
            for ol in r["output"].splitlines():
                lines.append(f"  > {ol}")
        lines.append("")
    if fake_pen:
        lines.append("## FAKE_PENETRATION 假穿透告警（变异后探针仍 PASS）")
        for fp in fake_pen:
            lines.append(f"- **FAKE_PEN** {fp}")
        lines.append("")
    if expired:
        lines.append("## EXPIRED 实车/人工断言（关联代码已变更，待现场复核）")
        for e in expired:
            lines.append(f"- **EXPIRED** `[{e['id']}]` `field:{e['target']}@{e['date']}`（之后已有 {e['changed_count']} 个文件变更）")
        lines.append("")
    if results:
        lines.append(f"## 探针明细 · HYGIENE（格式与结构卫生：{hyg_pass}/{len(hyg)}）")
        if hyg:
            for r in hyg:
                lines.append(f"- [{'PASS' if r['ok'] else 'FAIL'}] `{r['name']}` — {r['summary']}")
        else:
            lines.append("- （无）")
        lines.append("")
        lines.append(f"## 探针明细 · ANCHORED（外部真值与河岸锚定：{anc_pass}/{len(anc)}）")
        if anc:
            for r in anc:
                lines.append(f"- [{'PASS' if r['ok'] else 'FAIL'}] `{r['name']}` — {r['summary']}")
        else:
            lines.append("- （无）")

    suspect_path = state_dir(root) / "suspect.md"
    suspect_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"check: {status} ({len(results) - len(failed)}/{len(results)} probes pass | {tier_summary}) -> {suspect_path}")
    seen_warns: set[str] = set()
    for a in parse_canon_atoms(root):
        if a.get("has_materialized"):
            for mp in extract_materialized_paths(a.get("materialized_text", "")):
                if (root / mp).exists() or (repo / mp).exists():
                    w = f"WARN [{a['id']}] `物化: {mp}` 已存在：已物化为代码/探针，可考虑撤出文本条文"
                    if w not in seen_warns:
                        seen_warns.add(w)
                        print(f"  {w}")
    for r in results:
        for w in r.get("warnings", []):
            if w not in seen_warns:
                seen_warns.add(w)
                print(f"  {w}")
    for r in failed:
        print(f"  FAIL [{r['kind']}] {r['name']}: {r['output'].splitlines()[0] if r['output'] else 'non-zero exit'}")
    for fp in fake_pen:
        print(f"  FAKE_PEN {fp}")
    return 1 if (failed or fake_pen) else 0


def _install_hook(root: Path, repo: Path) -> int:
    hooks = repo / ".git" / "hooks"
    if not hooks.is_dir():
        print(f"error: not a git repo: {repo}")
        return 2
    hook = hooks / "post-commit"
    snippet = f"\n# catnest reflex\npython3 {Path(__file__).resolve().parent.parent / 'catnest.py'} --root {root} check --repo {repo} --diff HEAD~1..HEAD >/dev/null 2>&1 || true\n"
    existing = hook.read_text("utf-8") if hook.exists() else "#!/bin/sh\n"
    if "catnest reflex" not in existing:
        hook.write_text(existing.rstrip() + "\n" + snippet, encoding="utf-8")
        hook.chmod(0o755)
    print(f"installed post-commit hook: {hook}")
    return 0
