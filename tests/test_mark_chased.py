import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "mark_chased.py"


class MarkChasedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "nested" / "chased.json"

    def run_cli(self, *args, today="2026-10-27"):
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--today", today, "--state", str(self.state)],
                              capture_output=True, text=True)

    def read(self):
        return json.loads(self.state.read_text())

    def test_creates_state_file_lazily(self):
        r = self.run_cli("notion:n1", "fathom:f1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), {"notion:n1": "2026-10-27", "fathom:f1": "2026-10-27"})
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertIn("2 item(s)", r.stdout)

    def test_overwrites_existing_key_and_keeps_others(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text(json.dumps({"notion:n1": "2026-10-20", "notion:n2": "2026-10-25"}))
        self.run_cli("notion:n1")
        self.assertEqual(self.read(), {"notion:n1": "2026-10-27", "notion:n2": "2026-10-25"})

    def test_prunes_entries_older_than_30_days(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text(json.dumps({
            "notion:old": "2026-09-26",     # 31 days: dropped
            "notion:edge": "2026-09-27",    # 30 days: kept
            "notion:bad": "garbage",        # unparseable: dropped
        }))
        self.run_cli("notion:n1")
        self.assertEqual(self.read(), {"notion:edge": "2026-09-27", "notion:n1": "2026-10-27"})

    def test_corrupt_state_is_reset(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("not json")
        self.run_cli("notion:n1")
        self.assertEqual(self.read(), {"notion:n1": "2026-10-27"})

    def test_non_object_state_is_reset(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("[1]")
        self.run_cli("notion:n1")
        self.assertEqual(self.read(), {"notion:n1": "2026-10-27"})

    def test_no_args_exits_2_with_usage(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)
        self.assertFalse(self.state.exists())

    def test_bad_today_exits_2(self):
        r = self.run_cli("notion:n1", today="soon")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
