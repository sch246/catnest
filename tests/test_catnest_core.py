import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from catnest_lib import load_roles_config, load_uses, render_roles_markdown, touch_key  # noqa: E402
from catnest_lib.recall import recall_items  # noqa: E402

CLI = [sys.executable, str(ROOT / "catnest.py")]


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*CLI, *args], capture_output=True, text=True, check=False)


class TestCatnestCore(unittest.TestCase):
    def test_canon_evidence_triad_and_intent_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nest = Path(td) / "nest"
            self.assertEqual(run_cli("init", str(nest), "--name", "t").returncode, 0)
            (nest / "logs" / "ev.md").write_text("# Log\nline2\nline3\n", encoding="utf-8")

            # 1. Legacy [意图] must FAIL (exempt privilege removed)
            (nest / "canon" / "01.md").write_text(
                "### [A1] 旧意图\n- **性质**：`[意图]`\n- **断言**：x\n"
                "- **锚点**：`logs/ev.md#L1`\n- **死亡条件**：宿主重写\n",
                encoding="utf-8",
            )
            p_hyg = [sys.executable, str(ROOT / "probes" / "probe_canon_hygiene.py"), "--root", str(nest)]
            r1 = subprocess.run(p_hyg, capture_output=True, text=True, check=False)
            self.assertNotEqual(r1.returncode, 0)
            self.assertIn("[意图]", r1.stdout)

            # 2. [河岸] without 证据:, [裁决] without 来由: (or only legacy 碰撞:), and tautological 死亡条件 must FAIL
            (nest / "canon" / "01.md").write_text(
                "### [B1] 缺证据河岸\n- **性质**：`[河岸]`\n- **断言**：x\n- **死亡条件**：宿主重写\n\n"
                "### [D1] 无来由裁决\n- **性质**：`[裁决]`\n- **断言**：x\n- **碰撞**：`logs/ev.md#L1`\n- **死亡条件**：宿主重写\n\n"
                "### [D2] 同义反复死法\n- **性质**：`[裁决]`\n- **断言**：x\n- **来由**：「用户明确拍板」\n- **死亡条件**：用户 Supersedes\n\n"
                "### [D3] 空泛被取代死法\n- **性质**：`[裁决]`\n- **断言**：x\n- **来由**：`logs/ev.md#L2`\n- **死亡条件**：被取代时失效\n",
                encoding="utf-8",
            )
            r2 = subprocess.run(p_hyg, capture_output=True, text=True, check=False)
            self.assertNotEqual(r2.returncode, 0)
            for bad_id in ("B1", "D1", "D2", "D3"):
                self.assertIn(bad_id, r2.stdout)

            # 3. Valid [河岸] + [裁决] (来由: quote / path#Lx-y / 证据: fallback) + [事实] + optional 物化: WARN (non-blocking)
            (nest / "probes" / "probe_dummy.py").write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
            (nest / "canon" / "01.md").write_text(
                "### [B1] 真河岸\n- **性质**：`[河岸]`\n- **断言**：禁止裸奔\n"
                "- **证据**：`logs/ev.md#L1-3`\n- **物化**：`probes/probe_not_yet.py`\n- **死亡条件**：宿主架构重写\n\n"
                "### [D1] 真裁决\n- **性质**：`[裁决]`\n- **断言**：走统一闸\n"
                "- **来由**：「先落统一闸」，`logs/ev.md#L2`\n- **物化**：`probes/probe_dummy.py`\n- **死亡条件**：统一闸耗时高于收益\n\n"
                "### [F1] 真事实\n- **性质**：`[事实]`\n- **断言**：探针存在\n"
                "- **锚点**：`probes/probe_dummy.py`\n- **死亡条件**：探针脚本下线移除\n",
                encoding="utf-8",
            )
            r3 = subprocess.run(p_hyg, capture_output=True, text=True, check=False)
            self.assertEqual(r3.returncode, 0, msg=r3.stdout + r3.stderr)
            self.assertIn("WARN [D1]", r3.stdout)
            self.assertIn("已物化为代码/探针，可考虑撤出文本条文", r3.stdout)
            self.assertNotIn("probe_not_yet.py", r3.stdout)

            r_chk = run_cli("--root", str(nest), "check", "--all")
            self.assertEqual(r_chk.returncode, 0, msg=r_chk.stdout)
            self.assertIn("WARN [D1]", r_chk.stdout)
            self.assertIn("已物化为代码/探针，可考虑撤出文本条文", r_chk.stdout)

            r_asm_hint = run_cli("--root", str(nest), "assemble", "orange")
            self.assertEqual(r_asm_hint.returncode, 0, msg=r_asm_hint.stdout)
            self.assertIn("写 canon 必带来由与可观察死法；能物化成代码/探针即撤出条文", r_asm_hint.stdout)
            self.assertNotIn("隐式四问", r_asm_hint.stdout)

    def test_unclosed_open_never_sinks_on_purr(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nest = Path(td) / "nest"
            run_cli("init", str(nest))
            (nest / "open" / "01-stale-done.md").write_text(
                "---\nlast_touched: 2020-01-01\n---\n# 普通旧交接\n内容\n", encoding="utf-8"
            )
            (nest / "open" / "02-unclosed.md").write_text(
                "---\nlast_touched: 2020-01-01\n---\n# [未闭合] 幕结构分叉\n内容\n", encoding="utf-8"
            )
            (nest / "open" / "03-en-unclosed.md").write_text(
                "---\nlast_touched: 2020-01-01\n---\n# Split [UNCLOSED]\nbody\n", encoding="utf-8"
            )
            (nest / "open" / "04-tension.md").write_text(
                "---\nlast_touched: 2020-01-01\n---\n# 采样方案\n- **张力**：精度 ↔ 帧率\n", encoding="utf-8"
            )
            r = run_cli("--root", str(nest), "purr", "--days", "14", "--apply")
            self.assertEqual(r.returncode, 0, msg=r.stdout)
            self.assertFalse((nest / "open" / "01-stale-done.md").exists())
            self.assertTrue((nest / "open" / "02-unclosed.md").exists())
            self.assertTrue((nest / "open" / "03-en-unclosed.md").exists())
            self.assertTrue((nest / "open" / "04-tension.md").exists())

    def test_riverbank_and_external_evidence_exempt_from_decay_and_assemble_task(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            docs = ws / "docs"
            docs.mkdir()
            (docs / "rework.md").write_text(
                "# 历史评审\n无关前言\n\n## 五幕结构返工实录\n第五幕强塞对偶矩阵导致观众断片，必须拆开。\n",
                encoding="utf-8",
            )
            (docs / "secret.py").write_text("五幕结构返工实录 = 1\n", encoding="utf-8")

            nest = ws / ".catnest"
            run_cli("init", str(nest), "--name", "math")
            boot_txt = (nest / "boot.md").read_text("utf-8") + (
                "\n## 外部证据源\n- `../docs/*.md`\n- `../docs/*.py`\n"
            )
            (nest / "boot.md").write_text(boot_txt, encoding="utf-8")
            canon_file = nest / "canon" / "01.md"
            canon_file.write_text(
                "### [DEC1] 幕结构推进裁决\n- **性质**：`[裁决]`\n- **断言**：五幕结构节奏按标准模板紧凑推进执行。\n"
                "- **碰撞**：`../docs/rework.md#L4-5`\n- **死亡条件**：x\n\n"
                "### [RB1] 幕结构断片河岸\n- **性质**：`[河岸]`\n- **断言**：五幕结构节奏过密引发断片严禁硬塞。\n"
                "- **证据**：`../docs/rework.md#L4-5`\n- **死亡条件**：x\n",
                encoding="utf-8",
            )
            old_ts = time.time() - 180 * 86400
            os.utime(canon_file, (old_ts, old_ts))
            os.utime(docs / "rework.md", (old_ts, old_ts))

            # Inflate DEC1 with 35 recent touches; RB1 has 0 touches and 180-day old mtime!
            now = time.time()
            for i in range(35):
                touch_key(nest, "DEC1", now=now - (40 - i) * 120)

            hits = recall_items(nest, "五幕结构节奏", top=6)
            ids = [h["id"] for h in hits]
            self.assertIn("RB1", ids)
            self.assertIn("DEC1", ids)
            self.assertLess(ids.index("RB1"), ids.index("DEC1"), f"Riverbank suppressed by touch loop: {hits}")

            ev_hits = recall_items(nest, "五幕结构返工对偶矩阵", top=5)
            ev_only = [h for h in ev_hits if h["kind"] == "evidence"]
            self.assertTrue(ev_only, f"External evidence not indexed: {ev_hits}")
            self.assertRegex(ev_only[0]["path"], r"^\.\./docs/rework\.md#L\d+-\d+$")
            self.assertFalse(any("secret.py" in h["path"] for h in ev_hits))

            # Verify `assemble orange --task` appends Top-5 collisions prioritizing riverbank/unclosed/evidence
            (nest / "open" / "t1.md").write_text("# [UNCLOSED] 五幕结构分叉\n张力: 容量 ↔ 时长\n", encoding="utf-8")
            r_asm = run_cli("--root", str(nest), "assemble", "orange", "--task", "五幕结构返工")
            self.assertEqual(r_asm.returncode, 0, msg=r_asm.stdout)
            self.assertIn("[TASK COLLISION: 五幕结构返工]", r_asm.stdout)
            self.assertIn("../docs/rework.md#L", r_asm.stdout)
            self.assertIn("RB1", r_asm.stdout)

    def test_probe_honest_tiers_and_single_source_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nest = Path(td) / "nest"
            run_cli("init", str(nest))
            # Probe without `# kind:` defaults to HYGIENE; explicit `# kind: ANCHORED` goes to ANCHORED
            (nest / "probes" / "probe_a.py").write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
            (nest / "probes" / "probe_b.py").write_text(
                "#!/usr/bin/env python3\n# kind: ANCHORED\nprint('ok')\n", encoding="utf-8"
            )
            r = run_cli("--root", str(nest), "check", "--all")
            self.assertEqual(r.returncode, 0, msg=r.stdout)
            self.assertIn("HYGIENE: 1/1 | ANCHORED: 1/1", r.stdout)
            suspect = (nest / "_state" / "suspect.md").read_text("utf-8")
            self.assertIn("HYGIENE: 1/1 | ANCHORED: 1/1", suspect)
            self.assertIn("## 探针明细 · HYGIENE", suspect)
            self.assertIn("## 探针明细 · ANCHORED", suspect)

        cfg = load_roles_config(ROOT)
        self.assertEqual((ROOT / "templates" / "roles.md").read_text("utf-8"), render_roles_markdown(cfg))

    def test_assemble_keeps_startup_context_within_default_memory_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nest = Path(td) / "nest"
            run_cli("init", str(nest))
            (nest / "boot.md").write_text(
                "# test\n\n## 猫配方\n- `orange`：`canon/large.md`, `canon/bytes.md`, `canon/short.md`\n",
                encoding="utf-8",
            )
            (nest / "canon" / "large.md").write_text("\n".join(f"大段事实 {i}" for i in range(190)), encoding="utf-8")
            (nest / "canon" / "bytes.md").write_text("\n".join("x" * 6000 for _ in range(5)), encoding="utf-8")
            (nest / "canon" / "short.md").write_text("关键索引事实\n", encoding="utf-8")

            r = run_cli("--root", str(nest), "assemble", "orange")
            self.assertEqual(r.returncode, 0, msg=r.stdout)
            self.assertLessEqual(len(r.stdout.splitlines()), 200)
            self.assertLessEqual(len(r.stdout.encode("utf-8")), 25_000)
            self.assertIn("关键索引事实", r.stdout)
            self.assertIn("canon/large.md", r.stdout)
            self.assertIn("canon/bytes.md", r.stdout)
            self.assertIn("按需读取", r.stdout)

            full = run_cli("--root", str(nest), "assemble", "orange", "--print")
            self.assertEqual(full.returncode, 0, msg=full.stdout)
            self.assertIn("大段事实 189", full.stdout)
            self.assertIn("x" * 6000, full.stdout)
            self.assertIn("forced full bundle", full.stdout)

    def test_assemble_keeps_failed_probe_warnings_ahead_of_recipe_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nest = Path(td) / "nest"
            run_cli("init", str(nest))
            (nest / "boot.md").write_text(
                "# test\n\n## 猫配方\n- `orange`：`canon/*.md`\n", encoding="utf-8"
            )
            (nest / "_state").mkdir(exist_ok=True)
            (nest / "_state" / "suspect.md").write_text(
                "## FAIL\n探针发现必须先处理的失效规则\n", encoding="utf-8"
            )
            (nest / "canon" / "large.md").write_text(
                "### [LARGE] 大型条目\n" + "\n".join(f"长文内容 {i}" for i in range(50)),
                encoding="utf-8",
            )

            result = run_cli("--root", str(nest), "assemble", "orange", "--role", "none", "--max-lines", "14")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("必须先处理的失效规则", result.stdout)
            self.assertIn("canon/large.md", result.stdout)
            self.assertNotIn("长文内容 49", result.stdout)

    def test_assemble_touches_only_recipe_files_in_loaded_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nest = Path(td) / "nest"
            run_cli("init", str(nest))
            (nest / "boot.md").write_text(
                "# test\n\n## 猫配方\n- `orange`：`canon/*.md`\n", encoding="utf-8"
            )
            (nest / "canon" / "large.md").write_text(
                "### [LARGE] 大型条目\n" + "\n".join(f"长文内容 {i}" for i in range(50)),
                encoding="utf-8",
            )
            (nest / "canon" / "short.md").write_text(
                "### [SHORT] 短条目\n- **断言**：已读内容。\n", encoding="utf-8"
            )

            result = run_cli("--root", str(nest), "assemble", "orange", "--role", "none", "--max-lines", "14")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("已读内容", result.stdout)
            self.assertIn("按需读取", result.stdout)

            uses = load_uses(nest)
            self.assertIn("SHORT", uses)
            self.assertNotIn("LARGE", uses)

    def test_note_one_way_inbox_collides_before_append_and_promotes_unclosed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nest = Path(td) / "nest"
            run_cli("init", str(nest))
            (nest / "canon" / "01.md").write_text(
                "### [RB9] 端口占用河岸\n- **性质**：`[河岸]`\n"
                "- **断言**：严禁第二个实例抢绑 5701 端口。\n"
                "- **证据**：`docs/runtime.md#L10`\n- **死亡条件**：端口隔离重写\n",
                encoding="utf-8",
            )
            r = run_cli("--root", str(nest), "note", "我想再起一个实例监听 5701 端口做测试", "--open")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            # Must collide against existing RB9 without matching the newly appended inbox line itself
            coll_block = r.stdout.split("--- [TASK COLLISION:", 1)[1]
            self.assertIn("RB9", coll_block)
            self.assertNotIn("inbox-", coll_block)

            inboxes = list((nest / "logs").glob("inbox-*.md"))
            self.assertEqual(len(inboxes), 1)
            self.assertIn("5701 端口", inboxes[0].read_text("utf-8"))

            cards = list((nest / "open").glob("idea-*.md"))
            self.assertEqual(len(cards), 1)
            card_txt = cards[0].read_text("utf-8")
            self.assertIn("[未闭合]", card_txt)
            self.assertIn("RB9", card_txt)

            # Promoted [未闭合] idea card must never auto-sink on purr --days 0 --apply
            r_purr = run_cli("--root", str(nest), "purr", "--days", "0", "--apply")
            self.assertEqual(r_purr.returncode, 0, msg=r_purr.stdout)
            self.assertTrue(cards[0].exists())


if __name__ == "__main__":
    unittest.main()
