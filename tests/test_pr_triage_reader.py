"""Tests for pr_triage_reader.py. Made-up data only (product-os#5, Q10)."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "pr_triage_reader.py"
sys.path.insert(0, str(SCRIPT.parent))
import pr_triage_reader as ptr  # noqa: E402

DATE = "2026-10-12"
RUN = "2026-10-12T06:40:00Z"


def made_up_pr(key, title="Made-up check"):
    return {
        "key": key,
        "label": "needs-human",
        "risk": "high",
        "reason": "Changes the checkout button.",
        "deploy": {"dev": "live", "staging": "live", "prod": "not-triggered"},
        "groups": [
            {"kind": "matter", "title": "Checks that matter", "minutes": 5,
             "checks": [{"id": "b1", "title": title, "step": "Open the demo page.",
                         "url": "https://demo.example.com/checkout"}]},
            {"kind": "proven", "title": "Already proven",
             "checks": [{"id": "b2", "title": "Rounds to 2 places", "proof_url": "https://example.com/test"}]},
        ],
    }


def page_md(k, prs, run_id=RUN, of=1):
    data = json.dumps({"schema": ptr.SCHEMA, "kind": "page", "run_id": run_id, "page": k, "of": of, "prs": prs},
                      indent=1)
    return f"<!-- pr-triage-view page={k} -->\n\n```json\n{data}\n```\n", data


NOTES = {"matter": "The main change. Test these.", "proven": "Optional."}


def build(prs_by_page, date=DATE, schema=ptr.SCHEMA, run_failed=False, group_notes=NOTES):
    """(index markdown, {page: markdown}) for made-up pages."""
    pages, entries, summaries = {}, [], {}
    for k, prs in enumerate(prs_by_page, 1):
        md, data = page_md(k, prs, of=len(prs_by_page))
        pages[k] = md
        entries.append({"page": k, "sha256": ptr.block_sha(data), "prs": list(prs)})
        for key in prs:
            summaries[key] = {"label": "needs-human", "title": "summary"}
    idx = {"schema": schema, "kind": "index", "run_id": RUN, "valid_for": date, "run_failed": run_failed,
           "trial": {"text": "TRIAL: keep testing as normal."}, "pages": entries, "prs": summaries}
    if group_notes is not None:
        idx["group_notes"] = group_notes
    return f"# Testing triage\n\n```json\n{json.dumps(idx, indent=1)}\n```\n", pages


def finder(pages):
    return lambda entry: [pages[entry["page"]]] if entry["page"] in pages else []


class EvaluateTest(unittest.TestCase):
    def test_ok_run_keeps_every_pr(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}, {"receipts#7": made_up_pr("receipts#7")}])
        out, line = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(list(out["prs"]), ["web-app#12", "receipts#7"])
        self.assertEqual(out["no_triage"], [])
        self.assertEqual(out["trial"], {"text": "TRIAL: keep testing as normal."})
        self.assertEqual(line, f"triage: ok, 2 PRs (run {RUN})")

    def test_unknown_version_is_unsupported(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}], schema="pr-triage-view/2")
        out, line = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(out["status"], "unsupported")
        self.assertEqual(out["prs"], {})
        self.assertEqual(line, "triage: unsupported (format version 2)")

    def test_stale_run(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}], date="2026-10-09")
        out, line = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(out["status"], "stale")
        self.assertEqual(out["prs"], {})
        self.assertEqual(line, "triage: stale (valid for 2026-10-09)")

    def test_failed_run_is_unavailable(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}], run_failed=True)
        with self.assertRaises(ptr.Unavailable):
            ptr.evaluate(body, finder(pages), DATE)

    def test_mismatched_comment_drops_its_page_whole(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12"), "web-app#13": made_up_pr("web-app#13")},
                             {"receipts#7": made_up_pr("receipts#7")}])
        pages[1] = pages[1].replace("Made-up check", "Tampered check", 1)
        out, line = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(list(out["prs"]), ["receipts#7"])
        self.assertEqual(out["no_triage"], ["web-app#12", "web-app#13"])
        self.assertIn("no triage today: 2 PRs", line)

    def test_missing_page_means_no_triage(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}])
        out, _ = ptr.evaluate(body, finder({}), DATE)
        self.assertEqual(out["prs"], {})
        self.assertEqual(out["no_triage"], ["web-app#12"])

    def test_group_notes_pass_through(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}])
        out, _ = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(out["group_notes"], NOTES)

    def test_bad_group_notes_become_empty(self):
        for bad in (None, ["x"], {"matter": 5}, {"matter": None}, "text"):
            body, pages = build([{"web-app#12": made_up_pr("web-app#12")}], group_notes=bad)
            out, _ = ptr.evaluate(body, finder(pages), DATE)
            self.assertEqual(out["status"], "ok")
            self.assertEqual(out["group_notes"], {})

    def test_group_notes_are_always_present(self):
        self.assertEqual(ptr.result("stale")["group_notes"], {})
        self.assertEqual(ptr.result("unavailable")["group_notes"], {})

    def test_personal_data_in_group_notes_makes_the_run_unavailable(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}],
                            group_notes={"matter": "Ask jane@realcompany.co.uk"})
        with self.assertRaises(ptr.Unavailable):
            ptr.evaluate(body, finder(pages), DATE)

    def test_personal_data_is_withheld(self):
        pr = made_up_pr("web-app#12")
        pr["reason"] = "Ask jane@realcompany.co.uk"
        body, pages = build([{"web-app#12": pr, "receipts#7": made_up_pr("receipts#7")}])
        out, line = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(list(out["prs"]), ["receipts#7"])
        self.assertEqual(out["withheld"], ["web-app#12"])
        self.assertIn("withheld: suspicious content (web-app#12)", line)

    def test_example_com_and_drama_numbers_are_fine(self):
        pr = made_up_pr("web-app#12")
        pr["reason"] = "Sign in as test@example.com, phone +44 7700 900123"
        body, pages = build([{"web-app#12": pr}])
        out, _ = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(list(out["prs"]), ["web-app#12"])

    def test_token_is_withheld(self):
        pr = made_up_pr("web-app#12")
        pr["groups"][0]["checks"][0]["step"] = "Use ghp_" + "a" * 36
        body, pages = build([{"web-app#12": pr}])
        out, _ = ptr.evaluate(body, finder(pages), DATE)
        self.assertEqual(out["withheld"], ["web-app#12"])


class OutputTest(unittest.TestCase):
    def test_html_in_strings_is_escaped_but_unchanged(self):
        pr = made_up_pr("web-app#12", title='</script><img src=x onerror="alert(1)"> & more')
        body, pages = build([{"web-app#12": pr}])
        out, _ = ptr.evaluate(body, finder(pages), DATE)
        text = ptr.dumps_safe(out)
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertNotIn("&", text)
        back = json.loads(text)
        self.assertEqual(back["prs"]["web-app#12"]["groups"][0]["checks"][0]["title"],
                         '</script><img src=x onerror="alert(1)"> & more')

    def test_cli_from_dir_writes_file_and_exits_0(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}])
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "view"
            src.mkdir()
            (src / "index.md").write_text(body)
            (src / "page-1.md").write_text(pages[1])
            out = Path(d) / "state" / f"triage-{DATE}.json"
            r = subprocess.run([sys.executable, str(SCRIPT), "--repo", "lenathome/product-os", "--brief-date", DATE,
                                "--out", str(out), "--from-dir", str(src)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), f"triage: ok, 1 PR (run {RUN})")
            self.assertEqual(list(json.loads(out.read_text())["prs"]), ["web-app#12"])


class GithubTest(unittest.TestCase):
    def fake_run(self, issues, comments, rc=0):
        def run(argv, **kw):
            path = argv[-1]
            data = issues if "/comments" not in path else comments
            return subprocess.CompletedProcess(argv, rc, stdout=json.dumps(data), stderr="")
        return run

    def issue(self, body, author="EtienneEkko"):
        return {"number": 9, "state": "open", "user": {"login": author}, "labels": [{"name": "pr-triage"}],
                "body": body}

    def test_only_etienne_comments_are_read(self):
        body, pages = build([{"web-app#12": made_up_pr("web-app#12")}])
        comments = [{"id": 1, "user": {"login": "someone-else"}, "body": pages[1]}]
        with mock.patch.object(ptr.subprocess, "run", self.fake_run([self.issue(body)], comments)):
            out, _ = ptr.read("lenathome/product-os", DATE)
        self.assertEqual(out["prs"], {})
        self.assertEqual(out["no_triage"], ["web-app#12"])
        comments[0]["user"]["login"] = "EtienneEkko"
        with mock.patch.object(ptr.subprocess, "run", self.fake_run([self.issue(body)], comments)):
            out, _ = ptr.read("lenathome/product-os", DATE)
        self.assertEqual(list(out["prs"]), ["web-app#12"])

    def test_issue_by_someone_else_is_ignored(self):
        body, _ = build([{"web-app#12": made_up_pr("web-app#12")}])
        with mock.patch.object(ptr.subprocess, "run", self.fake_run([self.issue(body, "someone-else")], [])):
            out, line = ptr.read("lenathome/product-os", DATE)
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(line, "triage: unavailable (no triage issue)")

    def test_gh_failure_is_unavailable(self):
        with mock.patch.object(ptr.subprocess, "run", self.fake_run([], [], rc=1)):
            out, line = ptr.read("lenathome/product-os", DATE)
        self.assertEqual(line, "triage: unavailable (gh failed)")

    def test_calls_are_get_only(self):
        seen = []

        def run(argv, **kw):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")
        with mock.patch.object(ptr.subprocess, "run", run):
            ptr.read("lenathome/product-os", DATE)
        self.assertTrue(seen)
        for argv in seen:
            self.assertEqual(argv[:4], ["gh", "api", "--method", "GET"])


if __name__ == "__main__":
    unittest.main()
