import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ack_task.py"
sys.path.insert(0, str(SCRIPT.parent))
import ack_task  # noqa: E402


class AckTaskTest(unittest.TestCase):
    def run_main(self, state: Path, *keys: str):
        with mock.patch.object(ack_task, "STATE_FILE", state), \
                mock.patch.object(sys, "argv", ["ack_task.py", *keys]):
            ack_task.main()

    def test_creates_state_file_lazily(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "nested" / "acknowledged-tasks.json"
            self.run_main(state, "3f0f93807de4813288a1d113b0cf1854")
            self.assertEqual(json.loads(state.read_text()), ["3f0f93807de4813288a1d113b0cf1854"])

    def test_no_duplicates_and_appends(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "acknowledged-tasks.json"
            self.run_main(state, "3f0f93807de4813288a1d113b0cf1854")
            self.run_main(state, "3f0f93807de4813288a1d113b0cf1854", "3f1f93807de481ddb16ff41dd88d5d4d")
            self.assertEqual(json.loads(state.read_text()), ["3f0f93807de4813288a1d113b0cf1854", "3f1f93807de481ddb16ff41dd88d5d4d"])

    def test_corrupt_state_is_reset(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "acknowledged-tasks.json"
            state.write_text("not json")
            self.run_main(state, "3f0f93807de48186aef7e2205f207cf2")
            self.assertEqual(json.loads(state.read_text()), ["3f0f93807de48186aef7e2205f207cf2"])

    def test_no_args_exits_2_with_usage(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env={"HOME": d})
            self.assertEqual(r.returncode, 2)
            self.assertIn("usage:", r.stderr)


if __name__ == "__main__":
    unittest.main()
