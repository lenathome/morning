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
        self.assertEqual(brief["testing"][0]["n"], 6)
        self.assertEqual(brief["testing"][1]["n"], 7)
        self.assertEqual(brief["ideas"]["strategic"][0]["items"][0]["n"], 8)
        self.assertEqual(brief["ideas"]["other"][0]["items"][0]["n"], 9)

    def test_number_map(self):
        _, numbers = render_brief.number_items(load())
        self.assertEqual(numbers["1"], {"kind": "notion", "id": "p1"})
        self.assertEqual(numbers["3"], {"kind": "notion", "id": "p3"})
        self.assertEqual(numbers["4"], {"kind": "fathom", "key": "k1"})
        self.assertEqual(numbers["6"], {"kind": "test", "key": "ekko-checkout#142"})
        self.assertEqual(numbers["7"], {"kind": "test", "key": "ekko-api#1300"})
        self.assertEqual(numbers["8"], {"kind": "notion", "id": "p4"})
        self.assertEqual(len(numbers), 9)

    def test_missing_lists_default_to_empty(self):
        brief, numbers = render_brief.number_items({"date": "d", "weekday_label": "w", "focus": "f"})
        self.assertEqual(numbers, {})
        self.assertEqual(brief["testing"], [])

    def test_missing_focus_is_rejected(self):
        with self.assertRaises(ValueError):
            render_brief.number_items({"date": "d", "weekday_label": "w", "focus": ""})

    def test_todo_without_id_is_rejected(self):
        b = load()
        del b["urgent"][0]["items"][0]["id"]
        with self.assertRaises(ValueError):
            render_brief.number_items(b)


    def test_testing_item_missing_field_is_rejected(self):
        for k in ("repo", "number", "url", "title"):
            b = load()
            del b["testing"][0][k]
            with self.assertRaisesRegex(ValueError, f"has no '{k}'"):
                render_brief.number_items(b)

    def test_testing_steps_must_be_non_empty_list_of_strings(self):
        for bad in (None, [], "one step", [1], [""]):
            b = load()
            b["testing"][0]["steps"] = bad
            with self.assertRaisesRegex(ValueError, "ekko-checkout#142.*steps"):
                render_brief.number_items(b)
        b = load()
        del b["testing"][0]["steps"]
        with self.assertRaisesRegex(ValueError, "steps"):
            render_brief.number_items(b)


class WaitingOnTest(unittest.TestCase):
    def test_defaults_to_empty(self):
        b = load()
        del b["projects"][0]["waiting_on"]
        brief, _ = render_brief.number_items(b)
        self.assertEqual(brief["projects"][0]["waiting_on"], [])

    def test_invalid_entries_name_the_project(self):
        for bad in ([{"text": "", "who": "A"}], [{"who": "A"}], [{"text": "x", "who": 3}], ["x"], "x"):
            b = load()
            b["projects"][0]["waiting_on"] = bad
            with self.assertRaisesRegex(ValueError, "PPP localisation"):
                render_brief.number_items(b)

    def test_who_may_be_empty_or_missing(self):
        b = load()
        b["projects"][0]["waiting_on"] = [{"text": "x", "who": ""}, {"text": "y"}]
        render_brief.number_items(b)

    def test_markdown_lists_entries_after_summary(self):
        brief, _ = render_brief.number_items(load())
        md = render_brief.to_markdown(brief)
        self.assertIn("Bilo is finishing the move.\n\nWaiting on others (2):\n\n"
                      "- Sign-off on the rounding copy (Simon and Baran)\n- Staging data refresh\n\n", md)

    def test_markdown_omits_when_empty(self):
        b = load()
        b["projects"][0]["waiting_on"] = []
        brief, _ = render_brief.number_items(b)
        self.assertNotIn("Waiting on others", render_brief.to_markdown(brief))

    def test_numbers_and_counts_unchanged(self):
        brief, numbers = render_brief.number_items(load())
        self.assertEqual(len(numbers), 9)
        self.assertEqual(render_brief.counts(brief)["max_number"], 9)

    def test_template_renders_waiting_on(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn("Waiting on others", html)
        self.assertIn("waiting on others", html)


class MarkdownTest(unittest.TestCase):
    def setUp(self):
        brief, _ = render_brief.number_items(load())
        self.md = render_brief.to_markdown(brief)

    def test_header_and_focus(self):
        self.assertTrue(self.md.startswith("# Morning brief - Thursday 01 Oct 2026\n"))
        self.assertIn("> **Today's focus:** Ship the thing.", self.md)

    def test_parent_group_has_blank_lines_around_italic_name(self):
        self.assertIn("\n*Moka launch actions (you):*\n\n2. Chase Simon (overdue since 17 Sep)  [Operational]\n", self.md)

    def test_pr_line_and_poke(self):
        self.assertIn("- [#1291](https://github.com/ekko-enviroconomy/ekko-api/pull/1291) fix(funds): convert unit prices (ekko-api) - stacked on #1290", self.md)
        self.assertIn("- ⚡ [#325](", self.md)

    def test_action_line(self):
        self.assertIn('4. [Email Jamie](https://fathom.video/calls/1?timestamp=2) (from "P&E team sync", 25 Sep)', self.md)

    def test_no_em_dash(self):
        self.assertNotIn("—", self.md)

    def test_section_order(self):
        order = ["## To do", "**Urgent today**", "**Coming up** - 1", "**Your actions**", "**Product actions**",
                 "## External meeting prep", "## PRs needing you", "## Testing", "## Ideas bank",
                 "**Strategic** - 1", "**Operational** - 1", "## Engineering progress"]
        pos = [self.md.index(h) for h in order]
        self.assertEqual(pos, sorted(pos))
        for old in ("## Urgent today", "## Open action items", "## To-dos", "This week", "**Later**"):
            self.assertNotIn(old, self.md)

    def test_coming_up_line_and_blank_after_heading(self):
        self.assertIn("**Coming up** - 1\n\n3. Revisit round-up (due 2 Oct)  [Operational]\n", self.md)

    def test_ideas_parent_group(self):
        self.assertIn("**Operational** - 1\n\n*Public documentation:*\n\n9. Link to methodology PDFs\n", self.md)

    def test_ideas_items_have_no_category_tags_and_section_is_operational(self):
        ideas_md = self.md.split("## Ideas bank")[1].split("## Engineering progress")[0]
        for line in ideas_md.splitlines():
            if re.match(r"\d+\. ", line):
                self.assertNotIn("[", line)
        template = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn('["Operational", ideas.other]', template)
        self.assertNotIn('["Other"', template)

    def test_testing_section(self):
        self.assertIn("## Testing\n\n6. [#142](https://github.com/ekko-enviroconomy/ekko-checkout/pull/142) "
                      "feat(sdk): translated checkout strings (ekko-checkout, Checkout translation pipeline)"
                      " - merged 1 Oct, live: dev, staging, prod\n"
                      "   - Open the staging checkout in tr-TR\n"
                      "   - Check the contribution line reads in Turkish\n"
                      "7. [#1300](", self.md)
        self.assertIn("   - Request a quote for 12.34 EUR on dev\n   - (steps inferred from the diff)\n", self.md)
        self.assertEqual(self.md.count("(steps inferred from the diff)"), 1)

    def test_empty_testing_section_omitted(self):
        b = load()
        b["testing"] = []
        brief, _ = render_brief.number_items(b)
        self.assertNotIn("## Testing", render_brief.to_markdown(brief))

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
        self.assertIn("**Operational** - 1", md)
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
        self.assertEqual(c["testing"], 2)
        self.assertEqual(c["max_number"], 9)
        self.assertEqual(c["urgent"], 2)


class HtmlTest(unittest.TestCase):
    def test_json_is_embedded_and_script_safe(self):
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief)
        self.assertIn('id="brief-data"', html)
        self.assertNotIn("DNS <records>", html)          # raw < must not reach the page
        self.assertIn("DNS \\u003crecords>", html)
        self.assertIn("<title>Morning brief</title>", html)

    def test_testing_tab_chip_and_escaped_step(self):
        b = load()
        b["testing"][0]["steps"] = ["<script>alert(1)</script>"]
        brief, _ = render_brief.number_items(b)
        html = render_brief.to_html(brief)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("\\u003cscript>alert(1)", html)
        self.assertIn('id: "testing", label: "Testing"', html)
        self.assertIn('label: "To test"', html)
        self.assertIn("Nothing merged recently that needs a manual test.", html)

    def test_tabs_are_todo_prs_testing_ideas_projects(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        ids = re.findall(r'\{ id: "(\w+)", label: "([^"]+)"', html)
        self.assertEqual(ids, [("todo", "To do"), ("prs", "PRs"), ("testing", "Testing"),
                               ("ideas", "Ideas bank"), ("projects", "Projects")])
        self.assertNotIn('tab: "today"', html)


class HtmlLayoutTest(unittest.TestCase):
    def test_wide_layout_breakpoint_and_project_details(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn("(min-width: 1100px)", html)
        self.assertIn("window.matchMedia", html)
        self.assertIn('el("details", { "class": "prow" }', html)
        self.assertIn('el("aside", { "class": "side"', html)


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
            self.assertEqual(m["numbers"]["9"], {"kind": "notion", "id": "p5"})
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
