import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "mark_in_progress.py"
sys.path.insert(0, str(SCRIPT.parent))
import mark_in_progress  # noqa: E402


class MarkInProgressTest(unittest.TestCase):
    def run_main(self, state: Path, *keys: str):
        with mock.patch.object(mark_in_progress, "STATE_FILE", state), \
                mock.patch.object(sys, "argv", ["mark_in_progress.py", *keys]):
            mark_in_progress.main()

    def test_creates_state_file_lazily(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "nested" / "in-progress.json"
            self.run_main(state, "abc123")
            self.assertEqual(json.loads(state.read_text()), ["abc123"])

    def test_no_duplicates_and_appends(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "in-progress.json"
            self.run_main(state, "a", "a")
            self.run_main(state, "a", "b")
            self.assertEqual(json.loads(state.read_text()), ["a", "b"])

    def test_corrupt_state_is_reset(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "in-progress.json"
            state.write_text("not json")
            self.run_main(state, "a")
            self.assertEqual(json.loads(state.read_text()), ["a"])

    def test_no_args_exits_2_with_usage(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env={"HOME": d})
            self.assertEqual(r.returncode, 2)
            self.assertIn("usage:", r.stderr)


if __name__ == "__main__":
    unittest.main()
