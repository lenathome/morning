"""Tests for triage_from_notion.py. Made-up and sample data only."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "triage_from_notion.py"
FIXTURE = ROOT / "tests" / "fixtures" / "notion-triage-sample.json"
sys.path.insert(0, str(SCRIPT.parent))
import render_brief  # noqa: E402
import triage_from_notion as tfn  # noqa: E402

DATE = "2026-10-26"


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def run_cli(raw_text, date=DATE):
    """Run the script on raw_text; return (exit code, stdout, parsed output file)."""
    with tempfile.TemporaryDirectory() as d:
        rows, out = Path(d) / "rows.json", Path(d) / "sub" / "triage.json"
        rows.write_text(raw_text, encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "--rows", str(rows), "--brief-date", date, "--out", str(out)],
                           capture_output=True, text=True)
        return r.returncode, r.stdout, json.loads(out.read_text(encoding="utf-8"))


def convert(data):
    return tfn.convert(json.dumps(data), DATE)


class HappyPathTest(unittest.TestCase):
    def test_fixture_through_cli(self):
        code, stdout, out = run_cli(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "triage: ok (3 PRs)\n")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["source"], "notion")
        self.assertEqual(out["valid_for"], DATE)
        self.assertIsNone(out["run_id"])
        self.assertTrue(out["read_at"].endswith("Z"))
        self.assertEqual(out["group_notes"], {})
        self.assertEqual(out["withheld"], [])
        self.assertEqual(list(out["prs"]), ["ekko-checkout#213", "ekko-api#1425", "ekko-checkout#197"])
        self.assertIn("banner", out["trial"])
        self.assertIn("unchanged", out["trial"]["detail"])

    def test_card_fields(self):
        out, _ = convert(sample())
        pr = out["prs"]["ekko-api#1425"]
        self.assertEqual(pr["title"], "chore(ppp): seed the day-one country allowlist [A8]")
        self.assertEqual(pr["label"], "Test by hand")
        self.assertEqual(pr["risk"], "high")
        self.assertEqual(pr["deploy"], {"dev": "live", "staging": "live", "prod": "live"})
        self.assertIs(pr["on_prod"], True)
        self.assertEqual(pr["totals"], {"checks": 10, "checks_that_matter": 4, "minutes": 30})
        self.assertEqual(pr["last_change"], "New")
        self.assertEqual(pr["changed_on"], "2026-10-24")
        self.assertEqual(pr["status"], "To test")
        self.assertEqual(pr["notes"], "")
        self.assertEqual(pr["notion_url"], "https://app.notion.com/p/403f93807de481d9bbebd8055f8e23ed")
        self.assertEqual(pr["pr_url"], "https://github.com/ekko-enviroconomy/ekko-api/pull/1425")
        self.assertIs(out["prs"]["ekko-checkout#213"]["on_prod"], False)

    def test_numbers_floats_and_nulls(self):
        data = sample()
        row = data["results"][0]
        row["Checks"], row["Checks that matter"], row["Minutes"] = 12.0, None, 19.6
        out, _ = convert(data)
        self.assertEqual(out["prs"]["ekko-checkout#213"]["totals"],
                         {"checks": 12, "checks_that_matter": None, "minutes": 20})

    def test_write_escapes_html_characters(self):
        data = sample()
        data["results"][0]["Notes"] = "a <b> & c"
        _, _, out = run_cli(json.dumps(data))
        self.assertEqual(out["prs"]["ekko-checkout#213"]["notes"], "a <b> & c")
        with tempfile.TemporaryDirectory() as d:
            rows, dest = Path(d) / "r.json", Path(d) / "o.json"
            rows.write_text(json.dumps(data), encoding="utf-8")
            subprocess.run([sys.executable, str(SCRIPT), "--rows", str(rows), "--brief-date", DATE, "--out", str(dest)],
                           capture_output=True, text=True)
            raw = dest.read_text(encoding="utf-8")
        self.assertNotIn("<b>", raw)
        self.assertIn("\\u003cb\\u003e", raw)


class FilterTest(unittest.TestCase):
    def test_off_list_rows_dropped(self):
        data = sample()
        data["results"][1]["On the Testing list"] = "__NO__"
        data["results"][2]["On the Testing list"] = None
        out, line = convert(data)
        self.assertEqual(list(out["prs"]), ["ekko-checkout#213"])
        self.assertEqual(line, "triage: ok (1 PR)")

    def test_bad_key_skipped_and_named(self):
        data = sample()
        data["results"][0]["Key"] = "Bad Key#x"
        data["results"][1]["Key"] = None
        out, line = convert(data)
        self.assertEqual(list(out["prs"]), ["ekko-checkout#197"])
        self.assertTrue(line.startswith("triage: ok (1 PR); skipped bad key: "))
        self.assertIn("ekko-checkout#213 feat(app)", line)
        self.assertIn("ekko-api#1425 chore(ppp)", line)

    def test_uppercase_and_malformed_keys_rejected(self):
        for bad in ("Ekko-api#1", "ekko-api#", "ekko-api#1a", "ekko_api#1", "a#1\n", "#1"):
            data = sample()
            data["results"][0]["Key"] = bad
            out, _ = convert(data)
            self.assertNotIn(bad, out["prs"], bad)


class SafetyTest(unittest.TestCase):
    def test_unsafe_urls_blanked(self):
        bad_notion = ["http://app.notion.com/x", "https://evil.example/x", "https://notion.so.evil.example/x",
                      "javascript:alert(1)", "https://app.notion.com.evil.example/x", "", None, 5]
        bad_pr = ["http://github.com/ekko-enviroconomy/a/pull/1", "https://github.com/someone-else/a/pull/1",
                  "https://github.com.evil.example/ekko-enviroconomy/a/pull/1", "javascript:alert(1)", "", None]
        for u in bad_notion:
            data = sample()
            data["results"][0]["url"] = u
            out, _ = convert(data)
            self.assertEqual(out["prs"]["ekko-checkout#213"]["notion_url"], "", u)
        for u in bad_pr:
            data = sample()
            data["results"][0]["Link"] = u
            out, _ = convert(data)
            self.assertEqual(out["prs"]["ekko-checkout#213"]["pr_url"], "", u)

    def test_good_notion_hosts_kept(self):
        for u in ("https://app.notion.com/a", "https://www.notion.so/a", "https://notion.so/a"):
            data = sample()
            data["results"][0]["url"] = u
            out, _ = convert(data)
            self.assertEqual(out["prs"]["ekko-checkout#213"]["notion_url"], u)

    def test_bare_app_notion_page_gets_p_segment(self):
        page_id = "403f93807de481d9bbebd8055f8e23ed"
        cases = {
            f"https://app.notion.com/{page_id}": f"https://app.notion.com/p/{page_id}",
            f"https://app.notion.com/{page_id}?pvs=4": f"https://app.notion.com/p/{page_id}?pvs=4",
            f"https://app.notion.com/p/{page_id}": f"https://app.notion.com/p/{page_id}",
            f"https://www.notion.so/{page_id}": f"https://www.notion.so/{page_id}",
            f"https://notion.so/{page_id}": f"https://notion.so/{page_id}",
            f"https://evil.example/{page_id}": "",
        }
        for u, want in cases.items():
            data = sample()
            data["results"][0]["url"] = u
            out, _ = convert(data)
            self.assertEqual(out["prs"]["ekko-checkout#213"]["notion_url"], want, u)

    def test_strings_cleaned_and_capped(self):
        data = sample()
        data["results"][0]["Notes"] = "x" * 900
        data["results"][0]["Status"] = "To\x00 te\x1bst\x07\nnow"
        data["results"][0]["Label"] = 42
        out, _ = convert(data)
        pr = out["prs"]["ekko-checkout#213"]
        self.assertEqual(len(pr["notes"]), 500)
        self.assertEqual(pr["status"], "To test now")
        self.assertEqual(pr["label"], "")

    def test_bad_date_blanked(self):
        data = sample()
        data["results"][0]["date:Changed on:start"] = "yesterday"
        out, _ = convert(data)
        self.assertEqual(out["prs"]["ekko-checkout#213"]["changed_on"], "")


class UnavailableTest(unittest.TestCase):
    def check(self, raw, reason):
        code, stdout, out = run_cli(raw)
        self.assertEqual(code, 0)
        self.assertEqual(stdout, f"triage: unavailable ({reason})\n")
        self.assertEqual(out, {"status": "unavailable", "reason": reason})

    def test_invalid_json(self):
        self.check("not json {", "rows file is not valid JSON")

    def test_no_results_list(self):
        self.check("{}", "rows file has no results list")
        self.check('{"results": {"a": 1}}', "rows file has no results list")
        self.check("[]", "rows file has no results list")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "t.json"
            r = subprocess.run([sys.executable, str(SCRIPT), "--rows", str(Path(d) / "nope.json"),
                                "--brief-date", DATE, "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "triage: unavailable (cannot read rows file)\n")
            self.assertEqual(json.loads(out.read_text())["status"], "unavailable")

    def test_bad_date_argument_exits_non_zero(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--rows", "x", "--brief-date", "26/10", "--out", "y"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


class RenderBriefJoinTest(unittest.TestCase):
    def brief(self, date=DATE):
        return {"date": date, "testing": [
            {"repo": "ekko-api", "number": 1425, "title": "x"},
            {"repo": "ekko-api", "number": 9, "title": "y"}]}

    def test_join_accepts_output(self):
        _, _, tri = run_cli(FIXTURE.read_text(encoding="utf-8"))
        page = render_brief.join_triage(self.brief(), tri)
        self.assertEqual(page["triage"]["status"], "ok")
        self.assertEqual(page["triage"]["trial"], tri["trial"])
        self.assertEqual(page["testing"][0]["triage"]["label"], "Test by hand")
        self.assertEqual(page["testing"][1]["triage_note"], "No triage today")

    def test_join_rejects_other_date(self):
        _, _, tri = run_cli(FIXTURE.read_text(encoding="utf-8"))
        page = render_brief.join_triage(self.brief("2026-10-27"), copy.deepcopy(tri))
        self.assertEqual(page["triage"]["status"], "stale")

    def test_join_with_unavailable_file(self):
        _, _, tri = run_cli("nope")
        page = render_brief.join_triage(self.brief(), tri)
        self.assertEqual(page["triage"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
