import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "parse_goals.py"
FIXTURE = ROOT / "tests" / "fixtures" / "goals-sample.md"
sys.path.insert(0, str(SCRIPT.parent))
import parse_goals  # noqa: E402


class ParseGoalsTest(unittest.TestCase):
    def setUp(self):
        self.out = parse_goals.parse_goals(FIXTURE.read_text())

    def test_frontmatter(self):
        self.assertEqual(self.out["quarter"], "Q9 2099")
        self.assertEqual(self.out["status"], "draft")
        self.assertEqual(self.out["status_note"], "Sample draft, waiting on feedback")

    def test_goal_titles_drop_the_number_prefix(self):
        self.assertEqual([g["title"] for g in self.out["goals"]], ["Ship the widget", "Tidy the garden"])

    def test_why_joins_paragraph_lines(self):
        self.assertEqual(self.out["goals"][0]["why"], "The widget unblocks two partners. It must be stable first.")

    def test_done_when_items_and_comment_stripping(self):
        self.assertEqual(self.out["goals"][0]["done_when"],
                         ["The widget is live and documented.", "Partner A sends the header."])
        self.assertEqual(self.out["goals"][1]["done_when"], ["All beds are weeded by [date to set]."])

    def test_not_doing_stops_before_the_next_section(self):
        self.assertEqual(self.out["not_doing"], ["The shed rebuild: waiting on planning.", "The pond."])

    def test_no_comment_text_leaks(self):
        self.assertNotIn("<!--", json.dumps(self.out))
        self.assertNotIn("fixture", json.dumps(self.out))

    def test_cli_prints_the_json(self):
        r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout), self.out)

    def test_cli_missing_file_exits_1(self):
        r = subprocess.run([sys.executable, str(SCRIPT), str(ROOT / "tests" / "fixtures" / "nope.md")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("error", r.stderr)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
