import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "render_brief.py"
FIXTURE = ROOT / "tests" / "fixtures" / "brief-sample.json"
sys.path.insert(0, str(SCRIPT.parent))
import render_brief  # noqa: E402


def load():
    return json.loads(FIXTURE.read_text())


class NumberingTest(unittest.TestCase):
    def test_running_sequence_across_sections(self):
        brief, numbers = render_brief.number_items(load())
        self.assertEqual(brief["urgent"][0]["items"][0]["n"], 1)
        self.assertEqual(brief["urgent"][1]["items"][0]["n"], 2)
        self.assertEqual(brief["todos"]["coming_up"][0]["items"][0]["n"], 3)
        self.assertEqual(brief["actions"]["yours"][0]["n"], 4)
        self.assertEqual(brief["actions"]["product"][0]["n"], 5)
        self.assertEqual(brief["ideas"]["strategic"][0]["items"][0]["n"], 6)
        self.assertEqual(brief["ideas"]["other"][0]["items"][0]["n"], 7)

    def test_number_map(self):
        _, numbers = render_brief.number_items(load())
        self.assertEqual(numbers["1"], {"kind": "notion", "id": "p1"})
        self.assertEqual(numbers["3"], {"kind": "notion", "id": "p3"})
        self.assertEqual(numbers["4"], {"kind": "fathom", "key": "k1"})
        self.assertEqual(len(numbers), 7)

    def test_missing_lists_default_to_empty(self):
        _, numbers = render_brief.number_items({"date": "d", "weekday_label": "w", "focus": "f"})
        self.assertEqual(numbers, {})

    def test_missing_focus_is_rejected(self):
        with self.assertRaises(ValueError):
            render_brief.number_items({"date": "d", "weekday_label": "w", "focus": ""})

    def test_todo_without_id_is_rejected(self):
        b = load()
        del b["urgent"][0]["items"][0]["id"]
        with self.assertRaises(ValueError):
            render_brief.number_items(b)


class MarkdownTest(unittest.TestCase):
    def setUp(self):
        brief, _ = render_brief.number_items(load())
        self.md = render_brief.to_markdown(brief)

    def test_header_and_focus(self):
        self.assertTrue(self.md.startswith("# Morning brief - Thursday 01 Oct 2026\n"))
        self.assertIn("> **Today's focus:** Ship the thing.", self.md)

    def test_parent_group_has_blank_lines_around_italic_name(self):
        self.assertIn("\n*Moka launch actions (Lena):*\n\n2. Chase Simon (overdue since 17 Sep)  [Operational]\n", self.md)

    def test_pr_line_and_poke(self):
        self.assertIn("- [#1291](https://github.com/ekko-enviroconomy/ekko-api/pull/1291) fix(funds): convert unit prices (ekko-api) - stacked on #1290", self.md)
        self.assertIn("- ⚡ [#325](", self.md)

    def test_action_line(self):
        self.assertIn('4. [Email Jamie](https://fathom.video/calls/1?timestamp=2) (from "P&E team sync", 25 Sep)', self.md)

    def test_no_em_dash(self):
        self.assertNotIn("—", self.md)

    def test_section_order(self):
        order = ["## To do", "**Urgent today**", "**Coming up** - 1", "**Your actions**", "**Product actions**",
                 "## External meeting prep", "## PRs needing you", "## Ideas bank",
                 "**Strategic** - 1", "**Other** - 1", "## Engineering progress"]
        pos = [self.md.index(h) for h in order]
        self.assertEqual(pos, sorted(pos))
        for old in ("## Urgent today", "## Open action items", "## To-dos", "This week", "**Later**"):
            self.assertNotIn(old, self.md)

    def test_coming_up_line_and_blank_after_heading(self):
        self.assertIn("**Coming up** - 1\n\n3. Revisit round-up (due 2 Oct)  [Operational]\n", self.md)

    def test_ideas_parent_group(self):
        self.assertIn("**Other** - 1\n\n*Public documentation:*\n\n7. Link to methodology PDFs  [Operational]\n", self.md)

    def test_empty_ideas_section_omitted(self):
        b = load()
        b["ideas"] = {"strategic": [], "other": []}
        brief, _ = render_brief.number_items(b)
        self.assertNotIn("## Ideas bank", render_brief.to_markdown(brief))

    def test_empty_ideas_subsection_omitted(self):
        b = load()
        b["ideas"]["strategic"] = []
        brief, _ = render_brief.number_items(b)
        md = render_brief.to_markdown(brief)
        self.assertIn("**Other** - 1", md)
        self.assertNotIn("**Strategic**", md)

    def test_empty_urgent_and_product_omitted(self):
        b = load()
        b["urgent"] = []
        b["actions"]["product"] = []
        brief, _ = render_brief.number_items(b)
        md = render_brief.to_markdown(brief)
        self.assertNotIn("**Urgent today**", md)
        self.assertNotIn("**Product actions**", md)

    def test_empty_your_actions_says_clean_slate(self):
        b = load()
        b["actions"]["yours"] = []
        brief, _ = render_brief.number_items(b)
        self.assertIn("Nothing carrying over on your own actions. Clean slate.", render_brief.to_markdown(brief))


class CountsTest(unittest.TestCase):
    def test_counts(self):
        brief, _ = render_brief.number_items(load())
        c = render_brief.counts(brief)
        self.assertEqual(c["coming_up"], 1)
        self.assertEqual(c["ideas"], 2)
        self.assertEqual(c["max_number"], 7)
        self.assertEqual(c["urgent"], 2)


class HtmlTest(unittest.TestCase):
    def test_json_is_embedded_and_script_safe(self):
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief)
        self.assertIn('id="brief-data"', html)
        self.assertNotIn("DNS <records>", html)          # raw < must not reach the page
        self.assertIn("DNS \\u003crecords>", html)
        self.assertIn("<title>Morning brief</title>", html)

    def test_tabs_are_todo_prs_ideas_projects(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        ids = re.findall(r'\{ id: "(\w+)", label: "([^"]+)"', html)
        self.assertEqual(ids, [("todo", "To do"), ("prs", "PRs"), ("ideas", "Ideas bank"), ("projects", "Projects")])
        self.assertNotIn('tab: "today"', html)


class CliTest(unittest.TestCase):
    def test_writes_three_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = subprocess.run(
                [sys.executable, str(SCRIPT), str(FIXTURE),
                 "--md", str(d / "b.md"), "--html", str(d / "b.html"), "--map", str(d / "m.json")],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((d / "b.md").read_text().startswith("# Morning brief"))
            self.assertIn("brief-data", (d / "b.html").read_text())
            m = json.loads((d / "m.json").read_text())
            self.assertEqual(m["date"], "2026-10-01")
            self.assertEqual(m["numbers"]["7"], {"kind": "notion", "id": "p5"})
            self.assertIn('"urgent": 2', r.stdout)

    def test_bad_input_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text('{"date": "d"}')
            r = subprocess.run([sys.executable, str(SCRIPT), str(bad), "--md", str(Path(d) / "x.md")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("weekday_label", r.stderr)


if __name__ == "__main__":
    unittest.main()
