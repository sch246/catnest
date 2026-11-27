import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from catnest_lib.trace import analyze_transcript, write_trace_report  # noqa: E402


class TestTraceCorrections(unittest.TestCase):
    def test_report_links_private_correction_and_followup_in_selected_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "nest"
            root.mkdir()
            transcript = root / "transcript.jsonl"
            transcript.write_text('{"type":"USER_INPUT","content":"base content"}\n', encoding="utf-8")
            full = root / "transcript_full.jsonl"
            utterance = "不要试图重写这段私聊正文，保持原样"
            full.write_text(
                "not-json\n\n"
                + json.dumps({"step_index": 4, "type": "USER_INPUT", "content": utterance}, ensure_ascii=False)
                + "\n"
                + json.dumps({"step_index": 5, "type": "ASSISTANT_RESPONSE", "content": "done"})
                + "\n"
                + json.dumps({"step_index": 6, "type": "USER_INPUT", "content": "继续"})
                + "\n",
                encoding="utf-8",
            )

            sig = analyze_transcript(transcript)
            report = write_trace_report(root, sig).read_text("utf-8")
            self.assertEqual(sig["transcript"], str(full.resolve()))
            self.assertEqual(sig["corrections"][0]["line"], 3)
            self.assertIn(f"{full.resolve()}#L3", report)
            self.assertIn(f"{full.resolve()}#L4-L4", report)
            self.assertNotIn(utterance, report)

    def test_report_uses_input_file_when_full_fallback_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "nest"
            root.mkdir()
            transcript = root / "transcript.jsonl"
            transcript.write_text(
                "\n" + json.dumps({"step_index": 91, "type": "USER_INPUT", "content": "不对，请停下"}) + "\n",
                encoding="utf-8",
            )

            sig = analyze_transcript(transcript)
            report = write_trace_report(root, sig).read_text("utf-8")
            self.assertEqual(sig["transcript"], str(transcript.resolve()))
            self.assertIn(f"{transcript.resolve()}#L2", report)


if __name__ == "__main__":
    unittest.main()
