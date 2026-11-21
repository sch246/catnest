#!/usr/bin/env python3
# watches: catnest.py, catnest_lib/*.py, README.md, open/*.md, boot.md
# atoms: D2, D3, R1
# mutate: catnest_lib/assemble.py::"## FAIL" in suspect_txt=>False
# summary: End-to-end behavioral contract probe for catnest.py (penetration, scoped expiry & README anti-drift)

from __future__ import annotations

import argparse
import json
import os
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

        # 4. assemble default bundle + role cards + suspect; cross-project --meta inbox isolation; trace signals
        r = run([*cli, "--root", str(sandbox), "assemble", "orange"])
        assert r.returncode == 0 and "[ROLE: main]" in r.stdout and "### [C1] 测试事实" in r.stdout, f"default bundle missing: {r.stdout}"
        r_fo = run([*cli, "--root", str(sandbox), "assemble", "orange", "--files-only"])
        assert r_fo.returncode == 0 and "### [C1] 测试事实" not in r_fo.stdout
        r_dep = run([*cli, "--root", str(sandbox), "assemble", "--role", "deputy"])
        assert r_dep.returncode == 0 and "[ROLE: deputy]" in r_dep.stdout and "stream was interrupted" in r_dep.stdout
        assert run([*cli, "--root", str(sandbox), "friction", "测试摩擦", "--kind", "miss", "--open"]).returncode == 0

        fake_engine = Path(td) / "engine_home"
        (fake_engine / "logs").mkdir(parents=True)
        env_meta = {**os.environ, "CATNEST_HOME": str(fake_engine)}
        r_meta = subprocess.run(
            [*cli, "--root", str(sandbox), "friction", "含私有业务词摩擦", "--kind", "bloat", "--meta"],
            capture_output=True, text=True, check=False, env=env_meta,
        )
        assert r_meta.returncode == 0
        assert (fake_engine / "_state" / "meta-inbox.md").is_file(), "cross-project --meta must stage into _state/meta-inbox.md"
        assert not list((fake_engine / "logs").glob("*.md")), "cross-project --meta must NOT pollute engine logs/"

        brain_dir = Path(td) / "brain"
        parent_log = brain_dir / "11111111-1111-1111-1111-111111111111" / ".system_generated" / "logs" / "transcript.jsonl"
        child_id = "22222222-2222-2222-2222-222222222222"
        child_log = brain_dir / child_id / ".system_generated" / "logs" / "transcript.jsonl"
        parent_log.parent.mkdir(parents=True)
        child_log.parent.mkdir(parents=True)
        parent_log.write_text(
            "\n".join([
                json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": "2026-11-21T01:00:00Z",
                            "tool_calls": [{"name": "invoke_subagent", "arguments": {"Role": "Heavy Runner"}}]}),
                json.dumps({"step_index": 2, "type": "GENERIC", "created_at": "2026-11-21T01:00:02Z",
                            "content": f'{{"conversationId": "{child_id}", "logAbsoluteUri": "file://{child_log}"}}'}),
                json.dumps({"step_index": 3, "type": "PLANNER_RESPONSE", "created_at": "2026-11-21T01:01:00Z",
                            "tool_calls": [
                                {"name": "read_file", "arguments": {"Path": "/tmp/a.jpg"}},
                                {"name": "read_file", "arguments": {"Path": "/tmp/b.py"}},
                                {"name": "read_file", "arguments": {"Path": "/tmp/c.py"}},
                            ]}),
            ]) + "\n",
            encoding="utf-8",
        )
        child_log.write_text(
            "\n".join([
                json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": "2026-11-21T01:00:05Z",
                            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "mvn test"}}]}),
                json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": "2026-11-21T01:06:00Z",
                            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "mvn test"}}]}),
                json.dumps({"step_index": 3, "type": "PLANNER_RESPONSE", "created_at": "2026-11-21T01:15:30Z",
                            "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "mvn test"}}]}),
                json.dumps({"step_index": 4, "type": "ERROR_MESSAGE", "created_at": "2026-11-21T01:16:00Z",
                            "content": "Error: The stream was interrupted. Please continue the task you were working on."}),
                json.dumps({"step_index": 5, "type": "ERROR_MESSAGE", "created_at": "2026-11-21T01:18:00Z",
                            "content": "Error: The stream was interrupted. Please continue the task you were working on."}),
                json.dumps({"step_index": 6, "type": "ERROR_MESSAGE", "created_at": "2026-11-21T01:20:00Z",
                            "content": "Error: The stream was interrupted. Please continue the task you were working on."}),
            ]) + "\n",
            encoding="utf-8",
        )
        r = run([*cli, "--root", str(sandbox), "purr", "--days", "0", "--transcript", str(parent_log), "--apply"])
        assert r.returncode == 0 and not list((sandbox / "open").glob("*.md"))
        trace_md = (sandbox / "_state" / "trace_signals.md").read_text("utf-8")
        assert (
            "Heavy Runner" in trace_md
            and "full_mvn_test" in trace_md
            and "断流死循环" in trace_md
            and "主控直读图片" in trace_md
            and "等子代理期间下场直读" in trace_md
        ), f"missed new trace signals: {trace_md}"

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
