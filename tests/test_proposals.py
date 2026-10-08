import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "proposals.py"
sys.path.insert(0, str(SCRIPT.parent))
import proposals  # noqa: E402

PROJECT = """---
name: PPP localisation
status: active
next_milestone: round-up decision
last_reviewed: 2026-09-01
---
## Where it is
Presets agreed.

## Open questions
- tiny-gap rule

## Recent decisions
- Presets agreed <!-- src: a -->

- Second decision

## Ruled out
"""

EMPTY = """---
name: Empty
next_milestone: x
---
## Where it is

## Open questions
"""


def item(**over):
    base = {"slug": "ppp", "kind": "append", "section": "Recent decisions",
            "text": "Round-up deferred", "source": "ai-log/2026-09-29.md, Fixes",
            "session_title": "PPP chat", "session_date": "2026-09-29"}
    base.update(over)
    return base


class ProposalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.projects = root / "projects"
        self.projects.mkdir()
        (self.projects / "ppp.md").write_text(PROJECT, encoding="utf-8")
        (self.projects / "empty.md").write_text(EMPTY, encoding="utf-8")
        self.state = root / "state" / "project-proposals.json"
        self.log = self.state.parent / "project-proposals-log.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, stdin=None, position="before"):
        common = ["--state", str(self.state), "--projects-dir", str(self.projects), "--today", "2026-09-29"]
        full = (common + list(argv)) if position == "before" else (list(argv[:1]) + common + list(argv[1:]))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["proposals.py"] + full), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin or "")), \
                redirect_stdout(out), redirect_stderr(err):
            proposals.main()
        return json.loads(out.getvalue()), err.getvalue()

    def add(self, *items):
        result, _ = self.run_cli("add", stdin=json.dumps(list(items)))
        return result

    def read_project(self, name="ppp"):
        return (self.projects / f"{name}.md").read_text(encoding="utf-8")

    def test_add_valid_and_list(self):
        result = self.add(item())
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["skipped"], [])
        [p], _ = self.run_cli("list")
        self.assertEqual(p["id"], result["added"][0])
        self.assertEqual(len(p["id"]), 12)
        self.assertTrue(p["created_at"].endswith("Z"))

    def test_options_after_subcommand(self):
        result, _ = self.run_cli("add", stdin=json.dumps([item()]), position="after")
        self.assertEqual(len(result["added"]), 1)

    def test_list_empty_when_no_state(self):
        self.assertEqual(self.run_cli("list")[0], [])

    def test_add_validation_skips_bad_items_but_keeps_batch(self):
        bad = [
            item(slug="nope"),
            item(section="Missing heading"),
            item(kind="frontmatter", field="missing_field", value="x"),
            item(kind="weird"),
            {k: v for k, v in item().items() if k != "source"},
            item(text=""),
        ]
        result, err = self.run_cli("add", stdin=json.dumps(bad + [item()]))
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual([s["item_index"] for s in result["skipped"]], [0, 1, 2, 3, 4, 5])
        self.assertIn("item 0 skipped", err)

    def test_dedupe_against_pending_batch_and_log(self):
        first = self.add(item())["added"]
        again = self.add(item())
        self.assertEqual(again["added"], [])
        self.assertIn("duplicate", again["skipped"][0]["reason"])
        within = self.add(item(text="other"), item(text="other"))
        self.assertEqual(len(within["added"]), 1)
        self.run_cli("reject", first[0])
        self.assertEqual(self.add(item())["added"], [])

    def test_skips_same_thing_worded_differently_across_sections(self):
        self.add(item(text="2026-09-29: Round-up deferred to w/c 8 Sep"))
        reworded = self.add(
            item(section="Open questions", text="2026-09-30: round-up deferred to w/c 8 Sep!"),
            item(text="Round-up deferred to w/c 8 Sep, tiny-gap rule contested"),
        )
        self.assertEqual(reworded["added"], [])
        self.assertTrue(all(s["reason"].startswith("duplicate: same as pending") for s in reworded["skipped"]))

    def test_skips_text_the_project_file_already_says(self):
        result = self.add(item(text="2026-09-29: Second decision"), item(section="Open questions", text="Tiny-gap rule"))
        self.assertEqual(result["added"], [])
        self.assertEqual(
            [s["reason"] for s in result["skipped"]],
            ["duplicate: already in ppp.md", "duplicate: already in ppp.md"],
        )

    def test_skips_frontmatter_value_already_set_or_pending(self):
        fm = dict(kind="frontmatter", field="next_milestone")
        self.assertEqual(self.add(item(value='"Round-up decision"', **fm))["added"], [])
        first = self.add(item(value="ship it", **fm))["added"]
        self.assertEqual(len(first), 1)
        self.assertEqual(self.add(item(value="'Ship it'", **fm))["added"], [])
        self.assertEqual(len(self.add(item(value="something else", **fm))["added"]), 1)

    def test_similar_but_different_text_is_kept(self):
        self.add(item(text="Round-up deferred to w/c 8 Sep"))
        other = self.add(item(text="Round-up now ships with presets"), item(slug="empty", section="Open questions", text="Round-up deferred to w/c 8 Sep"))
        self.assertEqual(len(other["added"]), 2)

    def test_accept_append_middle_section_leaves_others_untouched(self):
        pid = self.add(item())["added"][0]
        result, _ = self.run_cli("accept", pid)
        self.assertEqual(result, {"accepted": [pid], "unknown": []})
        expected = PROJECT.replace(
            "- Second decision\n",
            "- Second decision\n- Round-up deferred <!-- src: ai-log/2026-09-29.md, Fixes -->\n")
        expected = expected.replace("last_reviewed: 2026-09-01", "last_reviewed: 2026-09-29")
        self.assertEqual(self.read_project(), expected)
        self.assertEqual(self.run_cli("list")[0], [])
        [entry] = json.loads(self.log.read_text())
        self.assertEqual(entry["outcome"], "accepted")
        self.assertIn("resolved_at", entry)

    def test_accept_append_empty_section_at_eof(self):
        pid = self.add(item(slug="empty", section="Open questions", text="Q?"))["added"][0]
        self.run_cli("accept", pid)
        self.assertTrue(self.read_project("empty").endswith(
            "## Open questions\n- Q? <!-- src: ai-log/2026-09-29.md, Fixes -->\n"))

    def test_accept_append_empty_section_followed_by_blank(self):
        pid = self.add(item(slug="empty", section="Where it is", text="Now"))["added"][0]
        self.run_cli("accept", pid)
        text = self.read_project("empty")
        self.assertIn("## Where it is\n\n- Now <!-- src: ai-log/2026-09-29.md, Fixes -->\n\n## Open questions", text)

    def test_accept_append_section_with_no_bullets_uses_last_line(self):
        pid = self.add(item(section="Where it is", text="Extra"))["added"][0]
        self.run_cli("accept", pid)
        self.assertIn("Presets agreed.\n- Extra <!-- src: ai-log/2026-09-29.md, Fixes -->\n\n## Open questions",
                      self.read_project())

    def test_accept_frontmatter_and_last_reviewed(self):
        pid = self.add(item(kind="frontmatter", field="next_milestone", value="ship it",
                            section=None, text=None))["added"][0]
        self.run_cli("accept", pid)
        text = self.read_project()
        self.assertIn("next_milestone: ship it\n", text)
        self.assertIn("last_reviewed: 2026-09-29\n", text)
        self.assertNotIn("round-up decision", text)
        self.assertEqual(text.split("---")[2], PROJECT.split("---")[2])

    def test_no_last_reviewed_field_is_not_created(self):
        pid = self.add(item(slug="empty", kind="frontmatter", field="next_milestone", value="y",
                            section=None, text=None))["added"][0]
        self.run_cli("accept", pid)
        self.assertNotIn("last_reviewed", self.read_project("empty"))

    def test_last_reviewed_not_confused_with_prose(self):
        pid = self.add(item(text="last_reviewed: mention"))["added"][0]
        self.run_cli("accept", pid)
        self.assertEqual(self.read_project().count("last_reviewed: 2026-09-29"), 1)

    def test_reject(self):
        pid = self.add(item())["added"][0]
        result, _ = self.run_cli("reject", pid)
        self.assertEqual(result, {"rejected": [pid], "unknown": []})
        self.assertEqual(self.read_project(), PROJECT)
        self.assertEqual(self.run_cli("list")[0], [])
        [entry] = json.loads(self.log.read_text())
        self.assertEqual(entry["outcome"], "rejected")

    def test_unknown_id_warns_and_continues(self):
        pid = self.add(item())["added"][0]
        result, err = self.run_cli("accept", "deadbeef0000", pid)
        self.assertEqual(result, {"accepted": [pid], "unknown": ["deadbeef0000"]})
        self.assertIn("deadbeef0000", err)

    def test_accept_fails_cleanly_when_heading_gone(self):
        pid = self.add(item())["added"][0]
        (self.projects / "ppp.md").write_text(PROJECT.replace("## Recent decisions", "## Renamed"))
        result, err = self.run_cli("accept", pid)
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["failed"], [pid])
        self.assertEqual(len(self.run_cli("list")[0]), 1)

    def test_no_temp_files_left(self):
        self.add(item())
        self.assertEqual([p.name for p in self.state.parent.iterdir()], ["project-proposals.json"])


class CliTests(unittest.TestCase):
    def test_subprocess_add_and_list(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "projects").mkdir()
            (root / "projects" / "ppp.md").write_text(PROJECT)
            common = ["--state", str(root / "s" / "p.json"), "--projects-dir", str(root / "projects")]
            r = subprocess.run([sys.executable, str(SCRIPT), "add"] + common,
                               input=json.dumps([item()]), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(json.loads(r.stdout)["added"]), 1)
            r = subprocess.run([sys.executable, str(SCRIPT)] + common + ["list"], capture_output=True, text=True)
            self.assertEqual(len(json.loads(r.stdout)), 1)


if __name__ == "__main__":
    unittest.main()
