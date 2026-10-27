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
TRIAGE_BRIEF = ROOT / "tests" / "fixtures" / "brief-triage-sample.json"
sys.path.insert(0, str(SCRIPT.parent))
import render_brief  # noqa: E402


class TagNoteTest(unittest.TestCase):
    NOTE_TEXT = "Owner tags are alpha"

    def untag(self, b):
        for g in b["urgent"] + b["todos"]["coming_up"] + b["ideas"]["strategic"] + b["ideas"]["other"]:
            for i in g["items"]:
                i.pop("tag", None)
        for a in b["actions"]["yours"]:
            a.pop("tag", None)
        return b

    def test_no_alpha_note_in_md_shared_md_or_html_even_when_tagged(self):
        brief, _ = render_brief.number_items(load())
        self.assertTrue(any(i.get("tag") for g in brief["urgent"] for i in g["items"]))
        for shared in (False, True):
            md = render_brief.to_markdown(brief, shared=shared)
            self.assertNotIn(self.NOTE_TEXT, md)
            self.assertNotIn("alpha", md.lower())
            self.assertIn("## To do\n\n**Urgent today**", md)
        html = render_brief.to_html(brief)
        self.assertNotIn(self.NOTE_TEXT, html)
        self.assertNotIn("alpha_note", html)
        template = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertNotIn("alpha", template.lower())

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
        self.assertEqual([w["n"] for w in brief["waiting"]], [5, 6])
        self.assertEqual(brief["testing"][0]["n"], 7)
        self.assertEqual(brief["testing"][1]["n"], 8)
        self.assertEqual(brief["ideas"]["strategic"][0]["items"][0]["n"], 9)
        self.assertEqual(brief["ideas"]["other"][0]["items"][0]["n"], 10)

    def test_number_map(self):
        _, numbers = render_brief.number_items(load())
        self.assertEqual(numbers["1"], {"kind": "notion", "id": "p1"})
        self.assertEqual(numbers["3"], {"kind": "notion", "id": "p3"})
        self.assertEqual(numbers["4"], {"kind": "fathom", "key": "k1"})
        self.assertEqual(numbers["5"], {"kind": "notion", "id": "w1"})
        self.assertEqual(numbers["6"], {"kind": "fathom", "key": "k2"})
        self.assertEqual(numbers["7"], {"kind": "test", "key": "ekko-checkout#142"})
        self.assertEqual(numbers["8"], {"kind": "test", "key": "ekko-api#1300"})
        self.assertEqual(numbers["9"], {"kind": "notion", "id": "p4"})
        self.assertEqual(len(numbers), 10)

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


def waiting_item(**over):
    w = {"kind": "notion", "id": "wx", "text": "Reply", "who": "Simon", "url": "https://example.com/x",
         "since": "2026-10-20", "days": 7, "chase": False, "chase_reason": None, "chased_on": None}
    w.update(over)
    return w


def waiting_md(*items):
    b = load()
    b["waiting"] = list(items)
    brief, _ = render_brief.number_items(b)
    return render_brief.to_markdown(brief)


class WaitingTest(unittest.TestCase):
    def test_defaults_to_empty_and_is_optional(self):
        b = load()
        del b["waiting"]
        brief, numbers = render_brief.number_items(b)
        self.assertEqual(brief["waiting"], [])
        self.assertEqual(len(numbers), 8)

    def test_items_keep_the_order_given(self):
        b = load()
        b["waiting"] = [waiting_item(id="a", days=1), waiting_item(id="b", days=30), waiting_item(id="c", days=5)]
        brief, numbers = render_brief.number_items(b)
        self.assertEqual([numbers[str(w["n"])]["id"] for w in brief["waiting"]], ["a", "b", "c"])

    def test_numbered_after_yours_and_before_testing(self):
        brief, _ = render_brief.number_items(load())
        self.assertLess(brief["actions"]["yours"][-1]["n"], brief["waiting"][0]["n"])
        self.assertLess(brief["waiting"][-1]["n"], brief["testing"][0]["n"])

    def test_defaults_filled_on_optional_fields(self):
        b = load()
        b["waiting"] = [{"kind": "fathom", "key": "k", "text": "x", "since": "2026-10-01", "days": 0, "chase": False}]
        w = render_brief.number_items(b)[0]["waiting"][0]
        self.assertEqual((w["who"], w["url"], w["project"], w["chase_reason"], w["chased_on"]), ("", "", "", None, None))

    def test_invalid_items_name_the_problem(self):
        cases = [
            ("not an object", "x", "not an object"),
            ("no text", waiting_item(text=""), "no 'text'"),
            ("notion without id", waiting_item(id=""), "no 'id'"),
            ("fathom without key", waiting_item(kind="fathom", key=""), "no 'key'"),
            ("unknown kind", waiting_item(kind="slack"), "unknown kind"),
            ("missing kind", {k: v for k, v in waiting_item().items() if k != "kind"}, "unknown kind"),
            ("who not a string", waiting_item(who=3), "'who'"),
            ("url not a string", waiting_item(url=3), "'url'"),
            ("bad since", waiting_item(since="27 Oct"), "'since'"),
            ("impossible since", waiting_item(since="2026-13-40"), "'since'"),
            ("bad days", waiting_item(days=-1), "'days'"),
            ("days as text", waiting_item(days="7"), "'days'"),
            ("days as bool", waiting_item(days=True), "'days'"),
            ("chase as text", waiting_item(chase="yes"), "'chase'"),
            ("bad chase_reason", waiting_item(chase_reason=4), "'chase_reason'"),
            ("bad chased_on", waiting_item(chased_on="yesterday"), "'chased_on'"),
        ]
        for label, item, pattern in cases:
            b = load()
            b["waiting"] = [item]
            with self.assertRaisesRegex(ValueError, pattern, msg=label):
                render_brief.number_items(b)
        for k in ("since", "days", "chase"):
            b = load()
            w = waiting_item()
            del w[k]
            b["waiting"] = [w]
            with self.assertRaisesRegex(ValueError, f"'{k}'"):
                render_brief.number_items(b)

    def test_waiting_must_be_a_list(self):
        b = load()
        b["waiting"] = {"a": 1}
        with self.assertRaisesRegex(ValueError, "'waiting' is not a list"):
            render_brief.number_items(b)

    def test_actions_product_moved(self):
        b = load()
        b["actions"]["product"] = [{"key": "k", "text": "x", "url": "u", "meeting": "m", "date": "d"}]
        with self.assertRaisesRegex(ValueError, "actions.product moved to 'waiting'"):
            render_brief.number_items(b)
        b["actions"]["product"] = []
        brief, _ = render_brief.number_items(b)
        self.assertNotIn("product", brief["actions"])

    def test_project_waiting_on_moved_and_names_the_project(self):
        b = load()
        b["projects"][0]["waiting_on"] = [{"text": "x", "who": "A"}]
        with self.assertRaisesRegex(ValueError, "PPP localisation.*moved to 'waiting'"):
            render_brief.number_items(b)
        b["projects"][0]["waiting_on"] = []
        brief, _ = render_brief.number_items(b)
        self.assertNotIn("waiting_on", brief["projects"][0])

    def test_markdown_section_follows_your_actions_with_blank_lines(self):
        md = waiting_md(waiting_item())
        self.assertIn("**Your actions**\n\n4. [Email Jamie]", md)
        self.assertRegex(md, r"\n\n\*\*Waiting for others\*\*\n\n5\. \[Reply\]\(https://example\.com/x\) \(Simon\) - waiting 7 days\n\n## ")
        order = [md.index(h) for h in ("**Your actions**", "**Waiting for others**", "## External meeting prep")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("**Product actions**", md)

    def test_markdown_line_variants(self):
        cases = [
            (waiting_item(days=0), "5. [Reply](https://example.com/x) (Simon) - since today\n"),
            (waiting_item(days=1), "5. [Reply](https://example.com/x) (Simon) - waiting 1 day\n"),
            (waiting_item(days=12), "5. [Reply](https://example.com/x) (Simon) - waiting 12 days\n"),
            (waiting_item(chase=True, chase_reason="Moka go-live is 9 Oct"),
             "5. ⚡ [Reply](https://example.com/x) (Simon) - waiting 7 days; Moka go-live is 9 Oct\n"),
            (waiting_item(chase=True, chase_reason=None), "5. ⚡ [Reply](https://example.com/x) (Simon) - waiting 7 days\n"),
            (waiting_item(chase=True, chase_reason="waiting 7 days"),
             "5. ⚡ [Reply](https://example.com/x) (Simon) - waiting 7 days\n"),
            (waiting_item(chase=False, chase_reason="stale reason"),
             "5. [Reply](https://example.com/x) (Simon) - waiting 7 days\n"),
            (waiting_item(chased_on="2026-10-27"), "5. [Reply](https://example.com/x) (Simon) - waiting 7 days; chased 27 Oct\n"),
            (waiting_item(chased_on="2026-10-03"), "5. [Reply](https://example.com/x) (Simon) - waiting 7 days; chased 3 Oct\n"),
            (waiting_item(chase=True, chase_reason="Launch", chased_on="2026-09-27"),
             "5. ⚡ [Reply](https://example.com/x) (Simon) - waiting 7 days; Launch; chased 27 Sep\n"),
            (waiting_item(url=""), "5. Reply (Simon) - waiting 7 days\n"),
            (waiting_item(who=""), "5. [Reply](https://example.com/x) - waiting 7 days\n"),
            (waiting_item(url="", who="", chase=True), "5. ⚡ Reply - waiting 7 days\n"),
        ]
        for item, line in cases:
            self.assertIn(line, waiting_md(item), msg=line)

    def test_markdown_omits_the_section_when_empty(self):
        self.assertNotIn("Waiting for others", waiting_md())

    def test_markdown_project_block_has_the_count_line_only_when_n_above_0(self):
        brief, _ = render_brief.number_items(load())
        for shared in (False, True):
            md = render_brief.to_markdown(brief, shared=shared)
            self.assertIn("Bilo is finishing the move.\n\nWaiting for others: 1 (in To do)\n\n", md)
            self.assertNotIn("Waiting on others", md)
        b = load()
        b["waiting"][0]["project"] = ""
        brief, _ = render_brief.number_items(b)
        self.assertNotIn("(in To do)", render_brief.to_markdown(brief))

    def test_project_count_matches_the_project_name_only(self):
        b = load()
        b["waiting"] = [waiting_item(project="PPP localisation"), waiting_item(project="PPP localisation"),
                        waiting_item(project="Other project")]
        brief, _ = render_brief.number_items(b)
        self.assertIn("Waiting for others: 2 (in To do)", render_brief.to_markdown(brief))

    def test_counts(self):
        brief, _ = render_brief.number_items(load())
        c = render_brief.counts(brief)
        self.assertEqual((c["waiting"], c["waiting_chase"], c["actions"]), (2, 1, 1))
        self.assertEqual(c["max_number"], 10)

    def test_counts_without_waiting(self):
        b = load()
        b["waiting"] = []
        c = render_brief.counts(render_brief.number_items(b)[0])
        self.assertEqual((c["waiting"], c["waiting_chase"]), (0, 0))

    def test_html_has_the_section_the_project_pill_and_no_product_actions(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn('section("Waiting for others", openCount(waiting), waitingPanel(waiting), "waiting-for-others")', html)
        self.assertIn('href: "#waiting-for-others"', html)
        self.assertIn('waitingHere + " waiting for others"', html)
        self.assertIn('span("pill waiting", "⚡ chase")', html)
        self.assertNotIn("Product actions", html)
        self.assertNotIn("waiting_on", html)
        self.assertNotIn("waiting on others", html.lower())
        # the section sits after Your actions in the To do tab
        self.assertLess(html.index('section("Your actions"'), html.index('section("Waiting for others"'))
        brief, _ = render_brief.number_items(load())
        page = render_brief.to_html(brief)
        self.assertIn('"text": "Sign-off on the rounding copy"', page)
        self.assertIn('"project": "PPP localisation"', page)

    def test_overlay_homes_use_waiting_and_it_is_not_startable(self):
        t = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn('"yours", "waiting", "testing", "ideas"]', t)
        startable = re.search(r"var STARTABLE = \{([^}]*)\}", t).group(1)
        self.assertNotIn("waiting", startable)
        self.assertNotIn('"product"', t)
        self.assertNotIn("product:", t)

    def test_overlay_chased_status_clears_the_marker_without_striking_through(self):
        t = (ROOT / "scripts" / "brief_template.html").read_text()
        self.assertIn('rec.status === "chased" && hit.home === "waiting"', t)
        self.assertIn("item.chase = false; item.chased_today = true;", t)
        self.assertIn('span("", "chased today")', t)
        # only `done` sets the struck-through state
        self.assertEqual(t.count("item.done = true"), 1)

    @unittest.skipUnless(__import__("shutil").which("node"), "node not installed")
    def test_overlay_runs_in_node(self):
        """Run applyOverlay and waitingRow from the real template against a stub DOM."""
        t = (ROOT / "scripts" / "brief_template.html").read_text()
        brief, _ = render_brief.number_items(load())
        page = render_brief.to_html(brief)
        script = re.search(r"<script>\n\(function \(\) \{(.*)\}\)\(\);\n</script>", page, re.S).group(1)
        # skip the first render, and stop once the overlay functions are defined
        self.assertEqual(script.count("  renderTabs();\n"), 1)
        script = script.replace("  renderTabs();\n", "")
        self.assertEqual(script.count("  var shown = brief;"), 1)
        script = script.replace("  var shown = brief;", "  globalThis.__x = { applyOverlay: applyOverlay, waitingRow: waitingRow, brief: brief };\n  return;\n  var shown = brief;")
        js = ("const BRIEF = " + json.dumps(json.dumps(brief)) + ";\n" + STUB_DOM + "(function () {" + script + "})();\n"
              "const x = globalThis.__x;\n"
              "const d = x.applyOverlay(x.brief, {items: {5: {status: 'chased'}, 6: {status: 'started'}, 7: {status: 'chased'}}});\n"
              "const w = d.waiting[0];\n"
              "console.log(JSON.stringify({chase: w.chase, today: w.chased_today, done: !!w.done,\n"
              "  w2inprog: d.in_progress.length, w2still: d.waiting.length, testing7: !!d.testing[0].chased_today}));\n"
              "const row = x.waitingRow(w);\n"
              "console.log(JSON.stringify({text: row.textContent, cls: row.className}));\n")
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second = [json.loads(line) for line in r.stdout.strip().splitlines()]
        self.assertEqual(first, {"chase": False, "today": True, "done": False, "w2inprog": 0, "w2still": 2, "testing7": False})
        self.assertIn("chased today", second["text"])
        self.assertNotIn("⚡", second["text"])
        self.assertNotIn("done", second["cls"])


STUB_DOM = """
function mk(tag) {
  const n = { tag, children: [], attrs: {}, style: {}, className: "", _text: "", parentNode: null,
    classList: { add() {} }, addEventListener() {}, setAttribute(k, v) { this.attrs[k] = v; },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    set textContent(v) { this._text = String(v); this.children = []; },
    get textContent() { return this._text + this.children.map(c => c.textContent).join(""); } };
  return n;
}
globalThis.window = { claude: undefined, scrollY: 0 };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
globalThis.document = { body: mk("body"), activeElement: null, visibilityState: "hidden",
  createElement: mk, createTextNode: (t) => ({ textContent: String(t), children: [] }),
  getElementById(id) { return id === "brief-data" ? { textContent: BRIEF } : (id === "bg-data" ? { textContent: "null" } : mk("div")); },
  addEventListener() {} };
"""


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
        order = ["## To do", "**Urgent today**", "**Coming up** - 1", "**Your actions**", "**Waiting for others**",
                 "## External meeting prep", "## PRs needing you", "## Testing", "## Ideas bank",
                 "**Strategic** - 1", "**Operational** - 1", "## Engineering progress"]
        pos = [self.md.index(h) for h in order]
        self.assertEqual(pos, sorted(pos))
        for old in ("## Urgent today", "## Open action items", "## To-dos", "This week", "**Later**"):
            self.assertNotIn(old, self.md)

    def test_coming_up_line_and_blank_after_heading(self):
        self.assertIn("**Coming up** - 1\n\n3. Revisit round-up (due 2 Oct)  [Operational]\n", self.md)

    def test_ideas_parent_group(self):
        self.assertIn("**Operational** - 1\n\n*Public documentation:*\n\n10. Link to methodology PDFs\n", self.md)

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
        self.assertIn("## Testing\n\n7. [#142](https://github.com/ekko-enviroconomy/ekko-checkout/pull/142) "
                      "feat(sdk): translated checkout strings (ekko-checkout, Checkout translation pipeline)"
                      " - merged 1 Oct, live: dev, staging, prod\n"
                      "   - Open the staging checkout in tr-TR\n"
                      "   - Check the contribution line reads in Turkish\n"
                      "8. [#1300](", self.md)
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

    def test_empty_urgent_and_waiting_omitted(self):
        b = load()
        b["urgent"] = []
        b["waiting"] = []
        brief, _ = render_brief.number_items(b)
        md = render_brief.to_markdown(brief)
        self.assertNotIn("**Urgent today**", md)
        self.assertNotIn("**Waiting for others**", md)

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
        self.assertIn("9. Travel calculator [split: Maria]\n   *Maria mocks it up, you decide.*\n", self.md())

    def test_untagged_items_render_as_before(self):
        md = self.md()
        self.assertIn("\n*Moka launch actions (you):*\n\n2. Chase Simon (overdue since 17 Sep)  [Operational]\n\n**Coming up**", md)
        self.assertIn("4. [Email Jamie](https://fathom.video/calls/1?timestamp=2) "
                      "(from \"P&E team sync\", 25 Sep) [handoff: Kurt]\n", md)
        self.assertIn("6. [Schedule officers' call](https://fathom.video/calls/3?timestamp=4) - waiting 1 day\n", md)

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
            b["actions"]["yours"][0]["tag"] = bad
            with self.assertRaisesRegex(ValueError, "Email Jamie"):
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
        self.assertIn("10. Link to methodology PDFs", shared)

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
        self.assertEqual(c["max_number"], 10)
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

    def test_tabs_are_todo_prs_testing_ideas_projects_clients(self):
        html = (ROOT / "scripts" / "brief_template.html").read_text()
        ids = re.findall(r'\{ id: "(\w+)", label: "([^"]+)"', html)
        self.assertEqual(ids, [("todo", "To do"), ("prs", "PRs"), ("testing", "Testing"),
                               ("ideas", "Ideas bank"), ("projects", "Projects"), ("clients", "Clients")])
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
        self.assertIn('el("details", { "class": "prow" }', html)
        self.assertIn('el("aside", { "class": "todo-side"', html)


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
            self.assertEqual(m["numbers"]["10"], {"kind": "notion", "id": "p5"})
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
        self.assertEqual(brief["ideas"]["other"][0]["items"][0]["n"], 12)
        self.assertEqual(numbers["1"], {"kind": "notion", "id": "ip1"})
        self.assertEqual(numbers["2"], {"kind": "fathom", "key": "ipk1"})
        self.assertEqual(numbers["3"], {"kind": "notion", "id": "p1"})
        self.assertEqual(len(numbers), 12)
        c = render_brief.counts(brief)
        self.assertEqual(c["in_progress"], 2)
        self.assertEqual(c["max_number"], 12)

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

    def test_in_progress_follows_the_heading_directly(self):
        b = with_in_progress(IN_PROGRESS)
        brief, _ = render_brief.number_items(b)
        md = render_brief.to_markdown(brief)
        self.assertIn("## To do\n\n**In progress**", md)

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
        self.assertIn("inProgress = d.in_progress || []", t)
        self.assertIn('section("In progress", openCount(inProgress)', t)
        self.assertIn('i.kind === "fathom" ? actionRow(i) : todoRow(i, true)', t)
        self.assertNotIn("innerHTML", t)

    def test_template_two_columns_on_todo_only_with_in_progress(self):
        t = self.template()
        # the grid applies to the To do container only when it has both columns, from 1100px
        self.assertIn(".todo-cols.has-side { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);", t)
        self.assertIn(".todo-cols.has-side .todo-side { grid-column: 2; grid-row: 1; position: sticky;", t)
        self.assertIn('" has-side" : ""', t)
        self.assertIn("inProgress.length && main.length", t)
        self.assertIn("(min-width: 1100px)", t)
        # In progress comes first in the markup, so it leads on narrow screens
        self.assertLess(t.index('cols.push(el("aside", { "class": "todo-side"'),
                        t.index('cols.push(el("div", { "class": "todo-main"'))
        # no side column outside the To do tab, and no width-dependent JS
        self.assertNotIn(".wrap.has-side", t)
        self.assertNotIn("wideQuery", t)
        self.assertNotIn("matchMedia", t)
        self.assertNotIn('app.appendChild(side)', t)

    def test_projects_only_in_its_tab_and_clients_has_its_own(self):
        t = self.template()
        self.assertNotIn("projectsNode", t)
        self.assertNotIn("projectsContent", t)
        self.assertNotIn("(wide ? main", t)
        self.assertEqual(t.count("projectsTab"), 2)   # defined once, used once in TABS
        self.assertIn('build: clientsTab, count: partners.length', t)
        self.assertIn('"Partners - next actions"', t)
        proj = t[t.index("function projectsTab()"):t.index("function clientsTab()")]
        self.assertNotIn("partners", proj)

    def test_header_holds_goals_and_pills_in_order(self):
        t = self.template()
        self.assertIn("max-width: 1240px; margin-inline: auto", t)
        a = t.index("app.appendChild(header)")
        b = t.index("header.appendChild(goalsNode)")
        c = t.index("app.appendChild(tablist)")
        self.assertTrue(a < b < c)

    def test_todo_pill_counts_in_progress_at_every_width(self):
        t = self.template()
        # counts only what is still open: the live overlay marks done items, which drop out of every count
        self.assertIn("count: openCount(inProgress) + openCount(urgentItems)", t)
        self.assertNotIn("wide ? 0 : inProgress.length", t)
        self.assertNotIn("todoBaseCount", t)


class LiveOverlayTest(unittest.TestCase):
    def template(self):
        return (ROOT / "scripts" / "brief_template.html").read_text()

    def test_template_reads_the_overlay_doc_and_never_writes_it(self):
        t = self.template()
        self.assertIn('db.doc("brief-updates/" + String(brief.date).replace(/[^0-9-]/g, ""))', t)
        self.assertIn("overlayDoc.get()", t)
        self.assertNotIn("overlayDoc.set", t)
        # the overlay is untrusted: it is applied to a fresh copy of the original brief and shown as text only
        self.assertIn("JSON.parse(JSON.stringify(base))", t)
        self.assertNotIn("innerHTML", t)

    def test_template_polls_only_while_the_page_is_visible(self):
        t = self.template()
        self.assertIn('document.visibilityState === "visible"', t)
        self.assertIn("setInterval(pollOverlay, 30000)", t)
        self.assertIn('document.addEventListener("visibilitychange", pollOverlay)', t)
        # the first paint never waits for the db
        self.assertLess(t.index("renderTabs();\n\n  /* ---------- live overlay"), t.index("readOverlay();\n    setInterval"))

    def test_template_keeps_the_page_state_on_re_render(self):
        t = self.template()
        self.assertIn("window.scrollTo(0, scrollY)", t)
        # the per-check result controls are gone, so nothing may still refer to them
        self.assertNotIn("results.", t)
        self.assertNotIn("paintResults", t)

    def test_html_still_embeds_the_brief_for_the_overlay_to_start_from(self):
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief)
        self.assertIn('<script id="brief-data" type="application/json">{"date": "2026-10-01"', html)
        self.assertIn('"n": 1', html)
        self.assertNotIn("/*__BRIEF_JSON__*/", html)


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
            self.assertTrue(md[focus_end:].startswith("## Q4 2026 goals\n\n_Draft_\n\n"))
            self.assertIn("- **Harden the API**\n  - Why: Partners build on it.\n"
                          "  - Done when:\n    - Header is live.\n    - Re-quote ships.\n", md)
            self.assertIn("- **Explore Shopify**\n\n", md)
            self.assertNotIn("Not doing", md)
            self.assertNotIn("Waiting on feedback", md)

    def test_status_note_and_not_doing_are_not_displayed(self):
        brief, _ = render_brief.number_items(with_goals(GOALS))
        md = render_brief.to_markdown(brief)
        self.assertNotIn("Waiting on feedback", md)
        self.assertNotIn("Not doing", md)
        # The page embeds the brief JSON, so the raw text is in the data; what matters is that the
        # template has no element or label that renders it.
        html = render_brief.to_html(brief)
        self.assertNotIn("Not doing", html)
        for marker in ("gnote", "notdoing", "goals.status_note", "goals.not_doing"):
            self.assertNotIn(marker, html)

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


def made_up_triage(date="2026-10-01", status="ok"):
    """A made-up triage file in the shape triage_from_notion.py writes (one Notion row per PR)."""
    return {
        "valid_for": date, "status": status, "run_id": None,
        "trial": {"banner": "TRIAL: keep testing as normal."}, "group_notes": {}, "withheld": [],
        "prs": {"ekko-checkout#142": {
            "title": "</script><b>Copy</b>", "label": "Test by hand", "risk": "high",
            "deploy": {"dev": "live", "staging": "unknown", "prod": "not deployed"}, "on_prod": False,
            "totals": {"checks": 12, "checks_that_matter": 4, "minutes": 20},
            "last_change": "New", "changed_on": "2026-10-24", "status": "To test", "notes": "Ask Sam first",
            "notion_url": "https://app.notion.com/403f93807de4816c93eae1f43acc0150",
            "pr_url": "https://github.com/ekko-enviroconomy/ekko-checkout/pull/142"}},
    }


class TriageTest(unittest.TestCase):
    def brief(self):
        return render_brief.number_items(load())[0]

    def test_join_on_repo_and_number(self):
        page = render_brief.join_triage(self.brief(), made_up_triage())
        by_key = {f"{t['repo']}#{t['number']}": t for t in page["testing"]}
        self.assertEqual(by_key["ekko-checkout#142"]["triage"]["label"], "Test by hand")
        self.assertNotIn("triage", by_key["ekko-api#1300"])
        self.assertEqual(by_key["ekko-api#1300"]["triage_note"], "No triage today")
        self.assertEqual(page["triage"]["status"], "ok")
        self.assertEqual(page["triage"]["trial"], {"banner": "TRIAL: keep testing as normal."})
        self.assertIsNone(page["triage"]["run_id"])

    def test_bad_group_notes_are_dropped(self):
        for bad in (None, ["x"], {"matter": 5}):
            tri = made_up_triage()
            tri["group_notes"] = bad
            self.assertEqual(render_brief.join_triage(self.brief(), tri)["triage"]["group_notes"], {})

    def test_join_leaves_the_brief_untouched(self):
        brief = self.brief()
        before = json.dumps(brief, sort_keys=True)
        render_brief.join_triage(brief, made_up_triage())
        self.assertEqual(json.dumps(brief, sort_keys=True), before)

    def test_withheld_pr_says_so(self):
        tri = made_up_triage()
        tri["withheld"] = ["ekko-api#1300"]
        page = render_brief.join_triage(self.brief(), tri)
        t = [t for t in page["testing"] if t["number"] == 1300][0]
        self.assertIn("withheld", t["triage_note"])

    def test_stale_or_unavailable_run_joins_nothing(self):
        for tri in (made_up_triage(date="2026-09-30"), made_up_triage(status="unavailable"), {"status": "stale"}, None):
            page = render_brief.join_triage(self.brief(), tri)
            self.assertFalse(any("triage" in t for t in page["testing"]))
            self.assertNotEqual(page["triage"]["status"], "ok")

    def test_markdown_never_carries_triage(self):
        with tempfile.TemporaryDirectory() as d:
            tri = Path(d) / "triage.json"
            tri.write_text(json.dumps(made_up_triage()))
            md, shared, html, md0 = (Path(d) / n for n in ("a.md", "a.shared.md", "a.html", "b.md"))
            r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--md", str(md), "--shared-md", str(shared),
                                "--html", str(html), "--triage", str(tri)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--md", str(md0)], check=True,
                           capture_output=True)
            self.assertEqual(md.read_text(), md0.read_text())
            for f in (md, shared):
                self.assertNotIn("Ask Sam first", f.read_text())
                self.assertNotIn("TRIAL", f.read_text())
            page = html.read_text()
            self.assertIn("Ask Sam first", page)
            self.assertIn("app.notion.com", page)
            self.assertNotIn("</script><b>", page)

    def test_page_carries_the_triage_json_and_no_results_collection(self):
        page = render_brief.to_html(render_brief.join_triage(self.brief(), made_up_triage()))
        self.assertIn('"last_change": "New"', page)
        self.assertIn('"notion_url"', page)
        self.assertIn("Open checks in Notion", page)
        self.assertNotIn("triage-results", page)
        self.assertNotIn("pass / fail", page.lower())

    def test_template_only_follows_notion_https_links(self):
        tpl = render_brief.TEMPLATE.read_text()
        self.assertIn("app.notion.com", tpl)
        self.assertIn("www.notion.so", tpl)
        self.assertNotIn("innerHTML", tpl)

    def test_real_shape_fixture_joins_and_renders(self):
        brief = render_brief.number_items(json.loads(TRIAGE_BRIEF.read_text()))[0]
        tri = made_up_triage(date=brief["date"])
        tri["prs"] = {"shop-web#42": tri["prs"]["ekko-checkout#142"]}
        page = render_brief.join_triage(brief, tri)
        by_key = {f"{t['repo']}#{t['number']}": t for t in page["testing"]}
        self.assertEqual(by_key["shop-web#42"]["triage"]["status"], "To test")
        self.assertEqual(by_key["shop-web#41"]["triage_note"], "No triage today")

    def test_missing_triage_file_is_fine(self):
        with tempfile.TemporaryDirectory() as d:
            html = Path(d) / "a.html"
            r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--html", str(html),
                                "--triage", str(Path(d) / "nope.json")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('"status": "unavailable"', html.read_text())


if __name__ == "__main__":
    unittest.main()
