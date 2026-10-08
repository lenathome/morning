import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_etienne_issues as fei  # noqa: E402


def issue(number, author="EtienneEkko", title="Something", labels=("from-etienne",), body="body"):
    return {"number": number, "title": title, "url": f"https://github.com/lenathome/product-os/issues/{number}",
            "author": {"login": author}, "labels": [{"name": l} for l in labels],
            "updatedAt": "2026-10-08T09:00:00Z", "body": body}


def comment(cid, author="EtienneEkko", body="hi"):
    return {"id": cid, "author": {"login": author}, "createdAt": "2026-10-08T10:00:00Z",
            "body": body, "url": f"https://example.com/{cid}"}


class FetchEtienneIssuesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "nested" / "etienne-issues.json"
        self.issues = []
        self.comments = {}
        p = mock.patch.object(fei, "STATE_FILE", self.state)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(fei, "run_gh", side_effect=self.fake_gh)
        p.start()
        self.addCleanup(p.stop)

    def fake_gh(self, args):
        if args[:2] == ["issue", "list"]:
            return json.dumps(self.issues)
        if args[:2] == ["issue", "view"]:
            return json.dumps({"comments": self.comments.get(int(args[2]), [])})
        raise AssertionError(args)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fei.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def check(self, *argv):
        code, out, _ = self.run_main(*argv)
        self.assertEqual(code, 0)
        return json.loads(out)["items"]

    def test_new_issue_by_label_includes_only_etienne_comments(self):
        self.issues = [issue(5, body="please look")]
        self.comments[5] = [comment("c1"), comment("c2", author="lenathome")]
        items = self.check()
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual((it["number"], it["kind"], it["body"]), (5, "new", "please look"))
        self.assertEqual([c["id"] for c in it["new_comments"]], ["c1"])
        self.assertEqual(it["new_comments"][0]["author"], "EtienneEkko")
        self.assertEqual(set(it["new_comments"][0]), {"id", "author", "created_at", "body", "url"})

    def test_explicit_check_subcommand_matches_default(self):
        self.issues = [issue(5)]
        self.assertEqual(self.check(), self.check("check"))

    def test_title_prefix_qualifies_case_insensitive(self):
        self.issues = [issue(1, title="[From-Etienne] hello", labels=()),
                       issue(2, title="[FROM-ETIENNE] hi", labels=())]
        self.assertEqual([i["number"] for i in self.check()], [1, 2])

    def test_other_author_ignored(self):
        self.issues = [issue(3, author="someoneelse")]
        self.assertEqual(self.check(), [])

    def test_no_label_or_prefix_ignored(self):
        self.issues = [issue(4, labels=(), title="plain title")]
        self.assertEqual(self.check(), [])

    def test_authors_override(self):
        self.issues = [issue(6, author="other")]
        self.assertEqual([i["number"] for i in self.check("--authors", "other")], [6])

    def test_items_sorted_by_number(self):
        self.issues = [issue(9), issue(2)]
        self.assertEqual([i["number"] for i in self.check()], [2, 9])

    def test_after_mark_nothing_then_update_with_only_new_comment(self):
        self.issues = [issue(5)]
        self.comments[5] = [comment("c1")]
        code, out, _ = self.run_main("mark", "5")
        self.assertEqual((code, json.loads(out)), (0, {"marked": [5]}))
        self.assertEqual(self.check(), [])
        self.comments[5].append(comment("c2", body="more"))
        items = self.check()
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["kind"], items[0]["body"]), ("update", ""))
        self.assertEqual([c["id"] for c in items[0]["new_comments"]], ["c2"])

    def test_comment_by_lenathome_after_mark_yields_nothing(self):
        self.issues = [issue(5)]
        self.comments[5] = [comment("c1")]
        self.run_main("mark", "5")
        self.comments[5].append(comment("c2", author="lenathome"))
        self.assertEqual(self.check(), [])

    def test_check_does_not_write_state(self):
        self.issues = [issue(5)]
        self.check()
        self.assertFalse(self.state.exists())

    def test_mark_records_all_authors_and_keeps_other_state(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text(json.dumps({"issues": {"7": {"seen_comment_ids": ["x"], "seen_at": "t"}}}))
        self.comments[5] = [comment("c1"), comment("c2", author="lenathome")]
        self.run_main("mark", "5")
        data = json.loads(self.state.read_text())["issues"]
        self.assertEqual(data["5"]["seen_comment_ids"], ["c1", "c2"])
        self.assertTrue(data["5"]["seen_at"].endswith("Z"))
        self.assertEqual(data["7"], {"seen_comment_ids": ["x"], "seen_at": "t"})

    def test_forget_removes_entry(self):
        self.comments[5] = [comment("c1")]
        self.run_main("mark", "5", "6")
        code, out, _ = self.run_main("forget", "5")
        self.assertEqual((code, json.loads(out)), (0, {"forgotten": [5]}))
        self.assertEqual(list(json.loads(self.state.read_text())["issues"]), ["6"])

    def test_missing_state_is_empty_and_mark_creates_nested_dir(self):
        self.assertFalse(self.state.parent.exists())
        self.issues = [issue(5)]
        self.assertEqual(len(self.check()), 1)
        self.run_main("mark", "5")
        self.assertTrue(self.state.exists())

    def test_gh_failure_exits_1(self):
        err = subprocess.CalledProcessError(1, ["gh"], stderr="boom happened\nsecond line\n")
        with mock.patch.object(fei, "run_gh", side_effect=err):
            code, out, stderr = self.run_main("check")
        self.assertEqual(code, 1)
        self.assertEqual(stderr.strip(), "gh failed: boom happened")

    def test_mark_without_numbers_exits_2(self):
        code, _, _ = self.run_main("mark")
        self.assertEqual(code, 2)

    def test_mark_non_integer_exits_2(self):
        code, _, _ = self.run_main("mark", "abc")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
