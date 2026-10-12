import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ack_action.py"
sys.path.insert(0, str(SCRIPT.parent))
import ack_action  # noqa: E402


class AckActionTest(unittest.TestCase):
    def run_main(self, state: Path, in_progress: Path, *keys: str):
        with mock.patch.object(ack_action, "STATE_FILE", state), \
                mock.patch.object(ack_action, "IN_PROGRESS_FILE", in_progress), \
                mock.patch.object(sys, "argv", ["ack_action.py", *keys]):
            ack_action.main()

    def test_appends_without_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "acknowledged-actions.json"
            self.run_main(state, Path(d) / "in-progress.json", "a")
            self.run_main(state, Path(d) / "in-progress.json", "a", "b")
            self.assertEqual(json.loads(state.read_text()), ["a", "b"])

    def test_removes_acked_keys_from_in_progress(self):
        with tempfile.TemporaryDirectory() as d:
            state, prog = Path(d) / "acknowledged-actions.json", Path(d) / "in-progress.json"
            prog.write_text(json.dumps(["a", "b", "c"]))
            self.run_main(state, prog, "b", "zzz")
            self.assertEqual(json.loads(prog.read_text()), ["a", "c"])

    def test_missing_in_progress_file_is_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            state, prog = Path(d) / "acknowledged-actions.json", Path(d) / "in-progress.json"
            self.run_main(state, prog, "a")
            self.assertFalse(prog.exists())

    def test_corrupt_in_progress_file_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            state, prog = Path(d) / "acknowledged-actions.json", Path(d) / "in-progress.json"
            prog.write_text("not json")
            self.run_main(state, prog, "a")
            self.assertEqual(prog.read_text(), "not json")
            self.assertEqual(json.loads(state.read_text()), ["a"])

    def test_no_args_exits_2_with_usage(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env={"HOME": d})
            self.assertEqual(r.returncode, 2)
            self.assertIn("usage:", r.stderr)


if __name__ == "__main__":
    unittest.main()
