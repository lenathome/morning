import base64
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "render_brief.py"
FIXTURE = ROOT / "tests" / "fixtures" / "brief-sample.json"
sys.path.insert(0, str(SCRIPT.parent))
import render_brief  # noqa: E402


class AlphaNoteTest(unittest.TestCase):
    NOTE = "_Owner tags are alpha: a first guess at who could own each to-do, not yet reviewed._\n\n"

    def untag(self, b):
        for g in b["urgent"] + b["todos"]["coming_up"] + b["ideas"]["strategic"] + b["ideas"]["other"]:
            for i in g["items"]:
                i.pop("tag", None)
        for a in b["actions"]["yours"] + b["actions"]["product"]:
            a.pop("tag", None)
        return b

    def test_md_and_shared_md_have_the_note_once_under_the_to_do_heading(self):
        brief, _ = render_brief.number_items(load())
        for shared in (False, True):
            md = render_brief.to_markdown(brief, shared=shared)
            self.assertEqual(md.count(self.NOTE), 1)
            self.assertIn("## To do\n\n" + self.NOTE + "**Urgent today**", md)

    def test_html_embeds_the_note_once_and_template_shows_it(self):
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief)
        self.assertEqual(html.count(render_brief.ALPHA_NOTE), 1)
        template = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn("brief.alpha_note", template)
        self.assertIn('span("pill other", "alpha")', template)

    def test_no_note_when_nothing_is_tagged(self):
        brief, _ = render_brief.number_items(self.untag(load()))
        for shared in (False, True):
            self.assertNotIn("alpha", render_brief.to_markdown(brief, shared=shared))
        self.assertNotIn(render_brief.ALPHA_NOTE, render_brief.to_html(brief))
        self.assertNotIn('"alpha_note":', render_brief.to_html(brief))

    def test_numbering_is_unchanged(self):
        tagged, tagged_map = render_brief.number_items(load())
        plain, plain_map = render_brief.number_items(self.untag(load()))
        self.assertEqual(tagged_map, plain_map)
        self.assertEqual(render_brief.counts(tagged), render_brief.counts(plain))


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
                # a tag suffix is allowed; category tags are not
                self.assertNotIn("[", re.sub(r" \[(needs-Lena|split: [^\]]+|handoff: [^\]]+)\]$", "", line))
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


class TagTest(unittest.TestCase):
    def md(self, b=None):
        brief, _ = render_brief.number_items(b or load())
        return render_brief.to_markdown(brief)

    def test_needs_lena_tag_and_why_line(self):
        self.assertIn("1. Standalone urgent (due today)  [Operational] [needs-Lena]\n"
                      "   *Only you can sign this off.*\n", self.md())

    def test_action_tag_follows_the_link_line(self):
        self.assertIn('4. [Email Jamie](https://fathom.video/calls/1?timestamp=2) (from "P&E team sync", 25 Sep)'
                      ' [handoff: Kurt]\n   *A plain follow-up email.*\n', self.md())

    def test_ideas_tag_shows_although_categories_do_not(self):
        self.assertIn("8. Travel calculator [split: Maria]\n   *Maria mocks it up, you decide.*\n", self.md())

    def test_untagged_items_render_as_before(self):
        md = self.md()
        self.assertIn("\n*Moka launch actions (you):*\n\n2. Chase Simon (overdue since 17 Sep)  [Operational]\n\n**Coming up**", md)
        self.assertIn("5. [Schedule officers' call](https://fathom.video/calls/3?timestamp=4) "
                      "(from \"P&E team sync\", 30 Sep)\n", md)

    def test_tag_without_why_adds_no_line(self):
        b = load()
        b["urgent"][0]["items"][0]["tag"]["why"] = ""
        md = self.md(b)
        self.assertIn("[needs-Lena]\n\n", md)

    def test_two_digit_numbers_indent_the_why_line_under_the_item(self):
        brief, _ = render_brief.number_items(load())
        brief["urgent"][0]["items"][0]["n"] = 12
        self.assertEqual(render_brief._todo_line(brief["urgent"][0]["items"][0])[1], "    *Only you can sign this off.*")

    def test_html_embeds_the_tag_and_template_renders_it(self):
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief)
        self.assertIn('"verdict": "handoff"', html)
        template = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn("tagPill(item)", template)
        self.assertIn("tagPill(a)", template)
        self.assertIn(".pill.needs-lena", template)

    def test_unknown_verdict_names_the_item(self):
        b = load()
        b["urgent"][0]["items"][0]["tag"]["verdict"] = "you"
        with self.assertRaisesRegex(ValueError, "Standalone urgent.*unknown tag verdict"):
            render_brief.number_items(b)

    def test_split_and_handoff_need_who(self):
        for verdict in ("split", "handoff"):
            for who in ("", "  ", None):
                b = load()
                tag = {"verdict": verdict, "why": "x"}
                if who is not None:
                    tag["who"] = who
                b["todos"]["coming_up"][0]["items"][0]["tag"] = tag
                with self.assertRaisesRegex(ValueError, f"Revisit round-up.*'{verdict}' tag with no 'who'"):
                    render_brief.number_items(b)

    def test_needs_lena_may_have_empty_who(self):
        b = load()
        b["todos"]["coming_up"][0]["items"][0]["tag"] = {"verdict": "needs-lena"}
        self.assertIn("3. Revisit round-up (due 2 Oct)  [Operational] [needs-Lena]\n", self.md(b))

    def test_non_object_tag_and_non_string_fields_are_rejected(self):
        for bad in ("needs-lena", ["split"], {"verdict": "split", "who": 3}, {"verdict": "needs-lena", "why": 4}):
            b = load()
            b["actions"]["product"][0]["tag"] = bad
            with self.assertRaisesRegex(ValueError, "Schedule officers' call"):
                render_brief.number_items(b)

    def test_ideas_item_with_bad_tag_is_rejected(self):
        b = load()
        b["ideas"]["other"][0]["items"][0]["tag"] = {"verdict": "handoff", "who": ""}
        with self.assertRaisesRegex(ValueError, "Link to methodology PDFs"):
            render_brief.number_items(b)

    def test_cli_exits_1_on_bad_tag(self):
        with tempfile.TemporaryDirectory() as d:
            b = load()
            b["urgent"][0]["items"][0]["tag"]["verdict"] = "nope"
            bad = Path(d) / "bad.json"
            bad.write_text(json.dumps(b))
            r = subprocess.run([sys.executable, str(SCRIPT), str(bad), "--md", str(Path(d) / "x.md")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("Standalone urgent", r.stderr)


class SharedMdTest(unittest.TestCase):
    def test_drops_only_external_meeting_prep(self):
        brief, _ = render_brief.number_items(load())
        full = render_brief.to_markdown(brief)
        shared = render_brief.to_markdown(brief, shared=True)
        self.assertIn("## External meeting prep", full)
        self.assertNotIn("## External meeting prep", shared)
        self.assertNotIn("Jo Bloggs", shared)
        self.assertNotIn("Acme - payments", shared)
        section = full[full.index("## External meeting prep"):full.index("## PRs needing you")]
        self.assertEqual(full.replace(section, ""), shared)

    def test_numbering_is_identical(self):
        brief, _ = render_brief.number_items(load())
        shared = render_brief.to_markdown(brief, shared=True)
        self.assertIn("1. Standalone urgent", shared)
        self.assertIn("9. Link to methodology PDFs", shared)

    def test_cli_writes_shared_md(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--md", str(d / "b.md"),
                                "--shared-md", str(d / "b.shared.md")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("External meeting prep", (d / "b.md").read_text())
            self.assertNotIn("External meeting prep", (d / "b.shared.md").read_text())


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
        self.assertNotIn('label: "To test"', html)
        self.assertIn("Nothing merged recently that needs a manual test.", html)

    def test_tabs_are_todo_prs_testing_ideas_projects(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        ids = re.findall(r'\{ id: "(\w+)", label: "([^"]+)"', html)
        self.assertEqual(ids, [("todo", "To do"), ("prs", "PRs"), ("testing", "Testing"),
                               ("ideas", "Ideas bank"), ("projects", "Projects")])
        self.assertNotIn('tab: "today"', html)

    def test_pills_are_the_only_tab_bar(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn('el("div", { "class": "chips", role: "tablist"', html)
        self.assertIn('el("button", { "class": "chip", role: "tab"', html)
        self.assertNotIn('"class": "tab",', html)
        self.assertNotIn(".tabs {", html)
        for old in ('label: "Urgent"', 'label: "PRs needing you"', 'label: "Your actions"', 'label: "Meetings"'):
            self.assertNotIn(old, html)


class HtmlLayoutTest(unittest.TestCase):
    def test_wide_layout_breakpoint_and_project_details(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn("(min-width: 1100px)", html)
        self.assertIn("window.matchMedia", html)
        self.assertIn('el("details", { "class": "prow" }', html)
        self.assertIn('el("aside", { "class": "side"', html)


PNG_1X1 = (b"\x89PNG\r\n\x1a\n"
           + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
           + struct.pack(">I", zlib.crc32(b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)))
           + struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND")))


class SeasonTest(unittest.TestCase):
    def test_month_boundaries(self):
        cases = {"2026-02-28": "winter", "2026-03-01": "spring", "2026-05-31": "spring",
                 "2026-06-01": "summer", "2026-08-31": "summer", "2026-09-01": "autumn",
                 "2026-11-30": "autumn", "2026-12-01": "winter", "2026-01-15": "winter"}
        for date, season in cases.items():
            self.assertEqual(render_brief.season_for(date), season, date)

    def test_bad_date_raises(self):
        for bad in ("2026-13-01", "2026-00-01"):
            with self.assertRaises(ValueError):
                render_brief.season_for(bad)


class BackgroundTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_file_is_used_as_is(self):
        f = self.dir / "any.png"
        f.write_bytes(PNG_1X1)
        self.assertEqual(render_brief.pick_background(str(f), "2026-10-08"), f)

    def test_unsupported_file_is_ignored(self):
        f = self.dir / "any.gif"
        f.write_bytes(b"GIF89a")
        self.assertIsNone(render_brief.pick_background(str(f), "2026-10-08"))

    def test_dir_picks_by_season_and_extension_order(self):
        (self.dir / "autumn.png").write_bytes(PNG_1X1)
        (self.dir / "winter.png").write_bytes(PNG_1X1)
        self.assertEqual(render_brief.pick_background(str(self.dir), "2026-10-08"), self.dir / "autumn.png")
        (self.dir / "autumn.jpg").write_bytes(b"x")
        self.assertEqual(render_brief.pick_background(str(self.dir), "2026-10-08"), self.dir / "autumn.jpg")
        self.assertEqual(render_brief.pick_background(str(self.dir), "2026-01-08"), self.dir / "winter.png")

    def test_missing_is_none(self):
        self.assertIsNone(render_brief.pick_background(None, "2026-10-08"))
        self.assertIsNone(render_brief.pick_background(str(self.dir / "nope.jpg"), "2026-10-08"))
        self.assertIsNone(render_brief.pick_background(str(self.dir), "2026-10-08"))  # no autumn file
        self.assertIsNone(render_brief.pick_background(str(self.dir), "not-a-date"))

    def test_embed_in_html_only(self):
        f = self.dir / "autumn.png"
        f.write_bytes(PNG_1X1)
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief, f)
        self.assertIn('id="bg-data"', html)
        self.assertIn('"data:image/png;base64,' + base64.b64encode(PNG_1X1).decode(), html)
        self.assertNotIn("/*__BG__*/", html)
        self.assertNotIn("data:image", render_brief.to_markdown(brief))

    def test_no_background_means_no_data_image(self):
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief)
        self.assertNotIn("data:image/", html)
        self.assertIn('id="bg-data" type="application/json">null</script>', html)

    def test_large_file_warns_on_stderr(self):
        f = self.dir / "big.jpg"
        f.write_bytes(b"\xff" * (601 * 1024))
        r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--html", str(self.dir / "b.html"),
                            "--background", str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("prep_background.sh", r.stderr)
        self.assertIn("data:image/jpeg;base64,", (self.dir / "b.html").read_text())

    def test_cli_small_background_no_warning_and_missing_option_unchanged(self):
        f = self.dir / "autumn.png"
        f.write_bytes(PNG_1X1)
        out = self.dir / "b.html"
        r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--html", str(out),
                            "--background", str(self.dir)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")  # fixture date 2026-10-01 is autumn
        self.assertIn("data:image/png", out.read_text())
        r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--html", str(out)],
                           capture_output=True, text=True)
        self.assertNotIn("data:image", out.read_text())

    def test_template_builds_the_layer_without_innerhtml(self):
        t = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn("style.backgroundImage = \"url(\" + JSON.stringify(bgUri) + \")\"", t)
        self.assertIn(".bg-photo { filter: brightness(0.55); }", t)
        self.assertNotIn("innerHTML", t)


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


IN_PROGRESS = [
    {"kind": "notion", "id": "ip1", "title": "Draft the SDK FAQ", "due": "due 3 Oct", "categories": ["Operational"],
     "note": "", "tag": {"verdict": "needs-lena", "who": "", "why": "Your call on the wording."}},
    {"kind": "fathom", "key": "ipk1", "text": "Send the deck", "url": "https://fathom.video/calls/9?timestamp=1",
     "meeting": "Partner call", "date": "2 Oct"},
]


def with_in_progress(items):
    b = load()
    b["in_progress"] = items
    return b


class InProgressTest(unittest.TestCase):
    def template(self):
        return (ROOT / "scripts" / "brief_template.html").read_text()

    def test_numbered_first_and_mapped_with_kind(self):
        brief, numbers = render_brief.number_items(with_in_progress(IN_PROGRESS))
        self.assertEqual([i["n"] for i in brief["in_progress"]], [1, 2])
        self.assertEqual(brief["urgent"][0]["items"][0]["n"], 3)
        self.assertEqual(brief["ideas"]["other"][0]["items"][0]["n"], 11)
        self.assertEqual(numbers["1"], {"kind": "notion", "id": "ip1"})
        self.assertEqual(numbers["2"], {"kind": "fathom", "key": "ipk1"})
        self.assertEqual(numbers["3"], {"kind": "notion", "id": "p1"})
        self.assertEqual(len(numbers), 11)
        c = render_brief.counts(brief)
        self.assertEqual(c["in_progress"], 2)
        self.assertEqual(c["max_number"], 11)

    def test_markdown_section_sits_before_urgent_with_matching_lines(self):
        brief, _ = render_brief.number_items(with_in_progress(IN_PROGRESS))
        for shared in (False, True):
            md = render_brief.to_markdown(brief, shared=shared)
            self.assertIn("**In progress**\n\n"
                          "1. Draft the SDK FAQ (due 3 Oct)  [Operational] [needs-Lena]\n"
                          "   *Your call on the wording.*\n"
                          '2. [Send the deck](https://fathom.video/calls/9?timestamp=1) (from "Partner call", 2 Oct)\n'
                          "\n**Urgent today**\n\n3. Standalone urgent", md)
            self.assertLess(md.index("## To do"), md.index("**In progress**"))
            self.assertLess(md.index("**In progress**"), md.index("**Urgent today**"))

    def test_note_comes_before_the_section_and_tags_count(self):
        b = with_in_progress(IN_PROGRESS)
        brief, _ = render_brief.number_items(b)
        md = render_brief.to_markdown(brief)
        self.assertIn("## To do\n\n_" + render_brief.ALPHA_NOTE + "_\n\n**In progress**", md)

    def test_absent_or_empty_renders_exactly_as_before(self):
        plain, plain_map = render_brief.number_items(load())
        for value in ([], None):
            b = load()
            b["in_progress"] = value
            brief, numbers = render_brief.number_items(b)
            self.assertEqual(numbers, plain_map)
            self.assertEqual(render_brief.to_markdown(brief), render_brief.to_markdown(plain))
            self.assertNotIn("In progress", render_brief.to_markdown(brief))
            self.assertEqual(render_brief.counts(brief), render_brief.counts(plain))

    def test_bad_shapes_name_the_problem(self):
        cases = [
            ("not a list", "x", "'in_progress' is not a list"),
            ("not an object", ["x"], "in_progress item 1 is not an object"),
            ("no kind", [{"id": "a", "title": "T"}], "unknown kind"),
            ("bad kind", [{"kind": "slack", "id": "a"}], "unknown kind 'slack'"),
            ("notion without id", [{"kind": "notion", "title": "Lost task"}], "Lost task.*no 'id'"),
            ("fathom without key", [{"kind": "fathom", "text": "Lost action"}], "Lost action.*no 'key'"),
            ("bad tag", [{"kind": "notion", "id": "a", "title": "Tagged", "tag": {"verdict": "you"}}],
             "Tagged.*unknown tag verdict"),
        ]
        for name, value, pattern in cases:
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, pattern):
                    render_brief.number_items(with_in_progress(value))

    def test_cli_exits_1_on_bad_in_progress(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "b.json"
            bad.write_text(json.dumps(with_in_progress([{"kind": "fathom", "text": "Lost action"}])))
            r = subprocess.run([sys.executable, str(SCRIPT), str(bad), "--md", str(Path(d) / "x.md")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("Lost action", r.stderr)

    def test_cli_map_carries_the_kinds(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "b.json"
            src.write_text(json.dumps(with_in_progress(IN_PROGRESS)))
            r = subprocess.run([sys.executable, str(SCRIPT), str(src), "--map", str(Path(d) / "m.json")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            m = json.loads((Path(d) / "m.json").read_text())["numbers"]
            self.assertEqual(m["2"], {"kind": "fathom", "key": "ipk1"})
            self.assertIn('"in_progress": 2', r.stdout)

    def test_html_embeds_the_items_and_template_builds_the_section(self):
        brief, _ = render_brief.number_items(with_in_progress(IN_PROGRESS))
        html = render_brief.to_html(brief)
        self.assertIn('"in_progress": [', html)
        self.assertIn('"kind": "fathom"', html)
        t = self.template()
        self.assertIn("brief.in_progress", t)
        self.assertIn('section("In progress", inProgress.length', t)
        self.assertIn('i.kind === "fathom" ? actionRow(i) : todoRow(i, true)', t)
        self.assertNotIn("innerHTML", t)

    def test_template_two_column_only_with_in_progress_and_projects_moves_to_main(self):
        t = self.template()
        # the grid only applies to a wrap that has a side column
        self.assertIn(".wrap.has-side { max-width: 1240px; display: grid;", t)
        self.assertNotRegex(t, r"\n  \.wrap \{ max-width: 1400px; display: grid")
        self.assertIn('app.classList.toggle("has-side", wide)', t)
        # no in-progress items: the side column is never added to the page
        self.assertIn("if (inProgressNode) app.appendChild(side)", t)
        self.assertIn("var inProgressNode = inProgress.length ?", t)
        # wide: projects at the bottom of the main column; narrow: back in its tab
        self.assertIn("(wide ? main : panels.projects).appendChild(projectsNode)", t)
        self.assertNotIn("(wide ? side : panels.projects)", t)
        # narrow: in progress is the first thing in the To do panel
        self.assertIn("panels.todo.insertBefore(inProgressNode, panels.todo.firstChild)", t)
        self.assertIn("(min-width: 1100px)", t)

    def test_todo_pill_counts_in_progress_only_while_it_is_in_the_panel(self):
        t = self.template()
        self.assertIn("todoBaseCount + (wide ? 0 : inProgress.length)", t)
        self.assertIn('{ id: "todo", label: "To do", build: todoTab, count: todoBaseCount', t)
        ids = re.findall(r'\{ id: "(\w+)", label: "([^"]+)"', t)
        self.assertEqual([i for i, _ in ids], ["todo", "prs", "testing", "ideas", "projects"])


GOALS = {
    "quarter": "Q4 2026", "status": "draft", "status_note": "Waiting on feedback",
    "goals": [
        {"title": "Harden the API", "why": "Partners build on it.", "done_when": ["Header is live.", "Re-quote ships."]},
        {"title": "Explore Shopify", "why": "", "done_when": []},
    ],
    "not_doing": ["The carbon update", "The Verra deal"],
}


def with_goals(goals):
    b = load()
    b["goals"] = goals
    return b


class GoalsTest(unittest.TestCase):
    def test_missing_goals_renders_as_before(self):
        brief, _ = render_brief.number_items(load())
        self.assertNotIn("goals", render_brief.to_markdown(brief))
        self.assertNotIn('"goals"', render_brief.to_html(brief))

    def test_goals_do_not_change_numbering_or_counts(self):
        plain, plain_map = render_brief.number_items(load())
        goaled, goaled_map = render_brief.number_items(with_goals(GOALS))
        self.assertEqual(plain_map, goaled_map)
        self.assertEqual(render_brief.counts(plain), render_brief.counts(goaled))

    def test_markdown_section_sits_right_after_the_focus_line(self):
        brief, _ = render_brief.number_items(with_goals(GOALS))
        for shared in (False, True):
            md = render_brief.to_markdown(brief, shared=shared)
            focus_end = md.index("\n\n", md.index("> **Today's focus:**")) + 2
            self.assertTrue(md[focus_end:].startswith("## Q4 2026 goals\n\n_Draft: Waiting on feedback_\n\n"))
            self.assertIn("- **Harden the API**\n  - Why: Partners build on it.\n"
                          "  - Done when:\n    - Header is live.\n    - Re-quote ships.\n", md)
            self.assertIn("- **Explore Shopify**\n\n", md)
            self.assertIn("Not doing: The carbon update; The Verra deal\n", md)

    def test_agreed_goals_have_no_draft_line(self):
        brief, _ = render_brief.number_items(with_goals({**GOALS, "status": "agreed"}))
        self.assertNotIn("Draft", render_brief.to_markdown(brief))

    def test_goal_lines_are_never_numbered(self):
        brief, _ = render_brief.number_items(with_goals(GOALS))
        md = render_brief.to_markdown(brief)
        section = md[md.index("## Q4 2026 goals"):md.index("## To do")]
        self.assertNotRegex(section, r"(?m)^\s*\d+\. ")

    def test_html_embeds_goals_and_template_builds_them_without_innerhtml(self):
        brief, _ = render_brief.number_items(with_goals(GOALS))
        self.assertIn('"quarter": "Q4 2026"', render_brief.to_html(brief))
        template = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn("goalsBlock(brief.goals)", template)
        self.assertNotIn("innerHTML", template)

    def test_bad_shapes_name_the_problem(self):
        cases = [
            ("not an object", ["x"], "'goals' is not an object"),
            ("no quarter", {**GOALS, "quarter": ""}, "quarter"),
            ("goals not a list", {**GOALS, "goals": "x"}, "'goals' is not a list"),
            ("empty title", {**GOALS, "goals": [{"title": " "}]}, "no 'title'"),
            ("bad done_when", {**GOALS, "goals": [{"title": "A", "done_when": "x"}]}, "done_when"),
            ("bad not_doing", {**GOALS, "not_doing": [1]}, "not_doing"),
        ]
        for name, goals, needle in cases:
            with self.subTest(name):
                with self.assertRaises(ValueError) as cm:
                    render_brief.number_items(with_goals(goals))
                self.assertIn(needle, str(cm.exception))

    def test_cli_exits_1_on_bad_goals(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "b.json"
            bad.write_text(json.dumps(with_goals({**GOALS, "goals": [{"title": ""}]})))
            r = subprocess.run([sys.executable, str(SCRIPT), str(bad), "--md", str(Path(d) / "x.md")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("title", r.stderr)


if __name__ == "__main__":
    unittest.main()
