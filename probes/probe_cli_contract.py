#!/usr/bin/env python3
# watches: catnest.py, catnest_lib/*.py, README.md, open/*.md, boot.md
# atoms: D2, D3, R1
# mutate: catnest_lib/assemble.py::"## FAIL" in suspect_txt=>False
# summary: End-to-end behavioral contract probe for catnest.py (penetration, scoped expiry & README anti-drift)

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repo", default=".")
    root = Path(ap.parse_args().root)
    cli = [sys.executable, str(root / "catnest.py")]

    with tempfile.TemporaryDirectory() as td:
        sandbox = Path(td) / "demo"
        assert run([*cli, "init", str(sandbox), "--name", "demo"]).returncode == 0

        # Create canon with alias + scoped field anchor + failing whisker probe
        (sandbox / "canon" / "01-core.md").write_text(
            "# Core\n\n### [C1] 测试事实\n- **性质**：`[事实]`\n- **断言**：必须能被召回与穿透。\n"
            "- **锚点**：`probes/probe_fail.py`, `field:car@2020-01-01(src/arm/*)`\n"
            "- **死亡条件**：探针或召回失效。\n- **别名**：暗语命中\n",
            encoding="utf-8",
        )
        (sandbox / "probes" / "probe_fail.py").write_text(
            "#!/usr/bin/env python3\n# watches: *\n# atoms: C1\n# summary: Deliberate fail\n"
            "import sys; print('boom'); sys.exit(1)\n",
            encoding="utf-8",
        )

        # 1. Alias recall (must NOT self-touch) -> assemble touches atom C1 -> real adoption = 1/1
        r = run([*cli, "--root", str(sandbox), "recall", "暗语命中", "--json"])
        assert r.returncode == 0
        hits = json.loads(r.stdout)
        assert hits and hits[0]["id"] == "C1", f"alias recall failed: {hits}"
        uses_file = sandbox / "_state" / "uses.json"
        assert not uses_file.exists(), "recall must not self-touch uses.json!"

        # 2. Scoped field expiry: unrelated commit must NOT expire field:car(src/arm/*)
        run(["git", "-C", str(sandbox), "init", "-q"])
        run(["git", "-C", str(sandbox), "config", "user.email", "test@local"])
        run(["git", "-C", str(sandbox), "config", "user.name", "test"])
        (sandbox / "README.md").write_text("unrelated\n", encoding="utf-8")
        run(["git", "-C", str(sandbox), "add", "README.md"])
        run(["git", "-C", str(sandbox), "commit", "-qm", "unrelated"])
        r = run([*cli, "--root", str(sandbox), "check", "--all"])
        assert r.returncode == 1
        suspect = (sandbox / "_state" / "suspect.md").read_text("utf-8")
        assert "## FAIL" in suspect and "## EXPIRED" not in suspect, f"false EXPIRED storm on unrelated commit: {suspect}"
        # Verify assemble attaches suspect when ONLY ## FAIL is present (and verify atom C1 adoption = 1/1)
        r_asm = run([*cli, "--root", str(sandbox), "assemble", "orange", "--json"])
        assert r_asm.returncode == 0 and json.loads(r_asm.stdout)["suspect_attached"] is True
        uses = json.loads((sandbox / "_state" / "uses.json").read_text("utf-8"))
        assert "C1" in uses, f"assemble failed to touch canon atom C1: {uses}"

        # 3. Matching commit under src/arm/ MUST expire field:car(src/arm/*)
        (sandbox / "src" / "arm").mkdir(parents=True)
        (sandbox / "src" / "arm" / "move.py").write_text("x = 1\n", encoding="utf-8")
        run(["git", "-C", str(sandbox), "add", "src/arm/move.py"])
        run(["git", "-C", str(sandbox), "commit", "-qm", "touch arm"])
        run([*cli, "--root", str(sandbox), "check", "--all"])
        suspect2 = (sandbox / "_state" / "suspect.md").read_text("utf-8")
        assert "## EXPIRED" in suspect2 and "field:car@2020-01-01" in suspect2, f"missed scoped EXPIRED: {suspect2}"

        # 4. assemble auto-attaches suspect; friction + purr alias sink stale open
        r = run([*cli, "--root", str(sandbox), "assemble", "orange", "--json"])
        assert r.returncode == 0 and json.loads(r.stdout)["suspect_attached"] is True
        assert run([*cli, "--root", str(sandbox), "friction", "测试摩擦", "--kind", "miss", "--open"]).returncode == 0
        r = run([*cli, "--root", str(sandbox), "purr", "--days", "0", "--apply"])
        assert r.returncode == 0 and not list((sandbox / "open").glob("*.md"))

    # 5. Anti-drift: README.md documented commands must match `catnest.py --help` & no stale `flow ` CLI residue
    help_txt = run([*cli, "--help"]).stdout
    readme = root / "README.md"
    assert readme.is_file(), "README.md missing (cold reader entry point)"
    rtxt = readme.read_text("utf-8")
    for cmd in ("init", "status", "assemble", "recall", "touch", "check", "friction", "purr", "settle"):
        assert f"`{cmd}" in rtxt and cmd in help_txt, f"CLI/README drift on command `{cmd}`"
    for p in [readme, root / "boot.md", *sorted((root / "open").glob("*.md"))]:
        txt = p.read_text("utf-8")
        assert "flow assemble" not in txt and "flow friction" not in txt, f"stale `flow` CLI name in {p.name}"

    print("OK: init/recall/adoption/scoped-expiry/penetration/assemble/friction/purr + README anti-drift passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
