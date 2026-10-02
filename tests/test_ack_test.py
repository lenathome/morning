import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ack_test.py"
sys.path.insert(0, str(SCRIPT.parent))
import ack_test  # noqa: E402


class AckTestTest(unittest.TestCase):
    def run_main(self, state: Path, *keys: str):
        with mock.patch.object(ack_test, "STATE_FILE", state), \
                mock.patch.object(sys, "argv", ["ack_test.py", *keys]):
            ack_test.main()

    def test_creates_state_file_lazily(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "nested" / "acknowledged-tests.json"
            self.run_main(state, "ekko-checkout#142")
            self.assertEqual(json.loads(state.read_text()), ["ekko-checkout#142"])

    def test_no_duplicates_and_appends(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "acknowledged-tests.json"
            self.run_main(state, "ekko-checkout#142")
            self.run_main(state, "ekko-checkout#142", "ekko-api#1300")
            self.assertEqual(json.loads(state.read_text()), ["ekko-checkout#142", "ekko-api#1300"])

    def test_corrupt_state_is_reset(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "acknowledged-tests.json"
            state.write_text("not json")
            self.run_main(state, "ekko-api#1")
            self.assertEqual(json.loads(state.read_text()), ["ekko-api#1"])

    def test_no_args_exits_2_with_usage(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env={"HOME": d})
            self.assertEqual(r.returncode, 2)
            self.assertIn("usage:", r.stderr)


if __name__ == "__main__":
    unittest.main()
