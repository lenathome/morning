import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "parse_projects.py"
sys.path.insert(0, str(SCRIPT.parent))
import parse_projects  # noqa: E402

TODAY = dt.date(2026, 9, 3)

FULL = """---
name: PPP localisation
status: active
owner: Lena
repos: [ekko-api, ekko-web-mono]
keywords: [ppp, round-up]
notion: https://www.notion.so/ekko-earth/ppp
next_milestone: round-up decision
target_date: 2026-09-12
last_reviewed: 2026-09-01
---
## Where it is
Presets agreed 2 Sep.

## Open questions
- tiny-gap rule
"""


def write(dirpath: Path, name: str, text: str) -> Path:
    p = dirpath / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class ParseFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parses_all_frontmatter_fields(self):
        p = write(self.dir, "ppp-localisation.md", FULL)
        r = parse_projects.parse_file(p, TODAY, 14)
        self.assertEqual(r["slug"], "ppp-localisation")
        self.assertEqual(r["name"], "PPP localisation")
        self.assertEqual(r["status"], "active")
        self.assertEqual(r["owner"], "Lena")
        self.assertEqual(r["repos"], ["ekko-api", "ekko-web-mono"])
        self.assertEqual(r["keywords"], ["ppp", "round-up"])
        self.assertEqual(r["notion"], "https://www.notion.so/ekko-earth/ppp")
        self.assertEqual(r["next_milestone"], "round-up decision")
        self.assertEqual(r["target_date"], "2026-09-12")
        self.assertEqual(r["last_reviewed"], "2026-09-01")
        self.assertFalse(r["stale"])
        self.assertTrue(r["body"].startswith("## Where it is"))

    def test_missing_optional_fields_default(self):
        p = write(self.dir, "bare.md", "---\nname: Bare\n---\nBody.\n")
        r = parse_projects.parse_file(p, TODAY, 14)
        self.assertEqual(r["status"], "unknown")
        self.assertIsNone(r["owner"])
        self.assertEqual(r["repos"], [])
        self.assertEqual(r["keywords"], [])
        self.assertIsNone(r["target_date"])
        self.assertIsNone(r["last_reviewed"])
        self.assertTrue(r["stale"])
        self.assertEqual(r["body"], "Body.")

    def test_stale_when_last_reviewed_older_than_threshold(self):
        old = FULL.replace("last_reviewed: 2026-09-01", "last_reviewed: 2026-08-01")
        p = write(self.dir, "old.md", old)
        self.assertTrue(parse_projects.parse_file(p, TODAY, 14)["stale"])

    def test_not_stale_on_threshold_day(self):
        edge = FULL.replace("last_reviewed: 2026-09-01", "last_reviewed: 2026-08-20")
        p = write(self.dir, "edge.md", edge)
        self.assertFalse(parse_projects.parse_file(p, TODAY, 14)["stale"])

    def test_no_frontmatter_returns_none(self):
        p = write(self.dir, "plain.md", "# Just a heading\n\ntext\n")
        self.assertIsNone(parse_projects.parse_file(p, TODAY, 14))


class ParseDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write(self.dir, "zeta.md", FULL.replace("PPP localisation", "Zeta"))
        write(self.dir, "alpha.md", FULL.replace("PPP localisation", "alpha"))
        write(self.dir, "_template.md", FULL.replace("PPP localisation", "Template"))
        write(self.dir, "_archive/done.md", FULL.replace("PPP localisation", "Done"))
        write(self.dir, "notes.txt", "not markdown")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ignores_underscore_files_and_archive_and_sorts_case_insensitively(self):
        names = [r["name"] for r in parse_projects.parse_dir(self.dir, TODAY, 14)]
        self.assertEqual(names, ["alpha", "Zeta"])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True,
        )

    def test_missing_dir_exits_1(self):
        r = self.run_cli("/nonexistent/projects")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found", r.stderr)

    def test_bad_yaml_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), "bad.md", "---\nname: [unclosed\n---\nbody\n")
            r = self.run_cli(d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("bad YAML", r.stderr)

    def test_outputs_json_array_with_today_override(self):
        with tempfile.TemporaryDirectory() as d:
            write(Path(d), "ppp.md", FULL)
            r = self.run_cli(d, "--today", "2026-12-01")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["stale"])


if __name__ == "__main__":
    unittest.main()
