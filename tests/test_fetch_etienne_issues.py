import contextlib
import io
import json
import subprocess
import sys
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


def comment(cid, author="EtienneEkko", body="hi", at="2026-10-08T10:00:00Z"):
    return {"id": cid, "author": {"login": author}, "createdAt": at,
            "body": body, "url": f"https://example.com/{cid}"}


class FetchEtienneIssuesTest(unittest.TestCase):
    def setUp(self):
        self.issues = []
        self.comments = {}
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

    def test_new_issue_by_label_includes_etienne_comments(self):
        self.issues = [issue(5, body="please look")]
        self.comments[5] = [comment("c1")]
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

    def test_new_when_no_comment_by_us(self):
        self.issues = [issue(5)]
        self.comments[5] = [comment("c1")]
        items = self.check()
        self.assertEqual([i["kind"] for i in items], ["new"])

    def test_update_only_comments_after_our_latest(self):
        self.issues = [issue(5)]
        self.comments[5] = [
            comment("c1", at="2026-10-08T09:00:00Z"),
            comment("c2", author="lenathome", at="2026-10-08T10:00:00Z"),
            comment("c3", at="2026-10-08T11:00:00Z", body="more"),
        ]
        items = self.check()
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["kind"], items[0]["body"]), ("update", ""))
        self.assertEqual([c["id"] for c in items[0]["new_comments"]], ["c3"])

    def test_nothing_after_our_comment_not_listed(self):
        self.issues = [issue(5)]
        self.comments[5] = [comment("c1", at="2026-10-08T09:00:00Z"),
                            comment("c2", author="lenathome", at="2026-10-08T10:00:00Z")]
        self.assertEqual(self.check(), [])

    def test_timestamps_compared_as_datetimes(self):
        self.issues = [issue(5)]
        self.comments[5] = [comment("c1", author="lenathome", at="2026-10-08T10:00:00+00:00"),
                            comment("c2", at="2026-10-08T10:00:00Z")]
        self.assertEqual(self.check(), [])

    def test_pending_lists_needs_lena_sorted(self):
        self.issues = [issue(9, labels=("from-etienne", "needs-lena")), issue(2, labels=("from-etienne",)),
                       issue(4, labels=("from-etienne", "needs-lena"), author="other")]
        code, out, _ = self.run_main("pending")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"items": [
            {"number": 9, "title": "Something", "url": "https://github.com/lenathome/product-os/issues/9"}]})

    def test_gh_failure_exits_1(self):
        err = subprocess.CalledProcessError(1, ["gh"], stderr="boom happened\nsecond line\n")
        with mock.patch.object(fei, "run_gh", side_effect=err):
            code, out, stderr = self.run_main("check")
        self.assertEqual(code, 1)
        self.assertEqual(stderr.strip(), "gh failed: boom happened")

    def test_unknown_flag_exits_2(self):
        code, _, _ = self.run_main("check", "--bogus")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
