#!/usr/bin/env python3
# watches: *
# atoms: T4
# mutate: boot.md::Project #0=>/root/work/secret-internal-proj
# summary: Guard open-source catnest repo against real-name git authors, local workspace paths, and credential tokens

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("local_workspace_path", re.compile(r"/root/work/(?!catnest\b)[A-Za-z0-9_.-]+")),
    ("private_lan_ip", re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")),
    ("credential_token", re.compile(r"\b(?:gho_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,})\b")),
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repo", default=".")
    root = Path(ap.parse_args().root)

    errors: list[str] = []

    if (root / ".git").exists():
        p_name = subprocess.run(
            ["git", "-C", str(root), "config", "user.name"],
            capture_output=True, text=True, check=False,
        )
        uname = p_name.stdout.strip()
        if not uname:
            errors.append("git user.name is unset (set GitHub handle, never real name)")
        elif CJK_RE.search(uname):
            errors.append(f"git user.name `{uname}` contains CJK characters (use GitHub handle, not real name)")

        p_log = subprocess.run(
            ["git", "-C", str(root), "log", "--format=%h:%an"],
            capture_output=True, text=True, check=False,
        )
        for ln in p_log.stdout.splitlines():
            if CJK_RE.search(ln):
                errors.append(f"commit author contains CJK characters (real-name risk): {ln}")

    skip_dirs = {".git", "_state", "__pycache__"}
    scanned = 0
    for f in root.rglob("*"):
        if not f.is_file() or any(part in skip_dirs for part in f.parts):
            continue
        if f.name == "probe_oss_privacy.py":
            continue
        scanned += 1
        txt = f.read_text("utf-8", errors="ignore")
        rel = f.relative_to(root)
        for kind, pat in LEAK_PATTERNS:
            m = pat.search(txt)
            if m:
                errors.append(f"{rel}: matched {kind} `{m.group(0)}`")

    if scanned == 0:
        errors.append("empty nest scanned")

    if errors:
        for e in errors:
            print(e)
        return 1
    print(f"OK: OSS privacy check passed across {scanned} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
