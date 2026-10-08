import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "publish_brief.sh"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": "/dev/null"}


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class PublishBriefTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.origin = tmp / "origin.git"
        self.clone = tmp / "clone"
        self.other = tmp / "other"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True, env=ENV)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)], check=True, env=ENV,
                       capture_output=True)
        git(self.clone, "checkout", "-q", "-B", "main")
        (self.clone / "README.md").write_text("product-os\n")
        (self.clone / "notes.md").write_text("notes\n")
        git(self.clone, "add", "README.md", "notes.md")
        git(self.clone, "commit", "-q", "-m", "init")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        self.src = tmp / "brief.shared.md"
        self.src.write_text("# Morning brief\n")

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, date="2026-10-08"):
        r = subprocess.run(["bash", str(SCRIPT), date, str(self.src), str(self.clone)],
                           capture_output=True, text=True, env=ENV)
        last = r.stdout.strip().splitlines()[-1]
        return r, json.loads(last)

    def origin_files(self):
        return git(self.origin, "ls-tree", "-r", "--name-only", "main").splitlines()

    def test_first_publish_commits_and_pushes(self):
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (True, True))
        self.assertEqual((self.clone / "briefs" / "latest.md").read_text(), "# Morning brief\n")
        self.assertIn("briefs/2026-10-08.md", self.origin_files())
        self.assertIn("briefs/latest.md", self.origin_files())
        self.assertEqual(git(self.origin, "log", "-1", "--format=%s", "main"), "brief 2026-10-08")

    def test_unrelated_dirty_file_is_not_committed(self):
        (self.clone / "notes.md").write_text("edited, not for sharing\n")
        (self.clone / "scratch.md").write_text("untracked\n")
        git(self.clone, "add", "notes.md")
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out["pushed"])
        changed = git(self.clone, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertEqual(sorted(changed), ["briefs/2026-10-08.md", "briefs/latest.md"])
        self.assertEqual(git(self.origin, "show", "main:notes.md"), "notes")
        status = git(self.clone, "status", "--porcelain")
        self.assertIn("M  notes.md", status)
        self.assertIn("?? scratch.md", status)

    def test_unpushed_commit_outside_briefs_skips_push(self):
        (self.clone / "notes.md").write_text("local only\n")
        git(self.clone, "add", "notes.md")
        git(self.clone, "commit", "-q", "-m", "wip notes")
        r, out = self.run_script()
        self.assertEqual(r.returncode, 2)
        self.assertIn("push skipped: unpushed commits outside briefs/", r.stdout)
        self.assertEqual((out["committed"], out["pushed"]), (True, False))
        self.assertNotIn("briefs/latest.md", self.origin_files())
        self.assertEqual(git(self.origin, "show", "main:notes.md"), "notes")

    def test_behind_origin_skips_push(self):
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.other)], check=True, env=ENV,
                       capture_output=True)
        (self.other / "README.md").write_text("changed upstream\n")
        git(self.other, "add", "README.md")
        git(self.other, "commit", "-q", "-m", "upstream")
        git(self.other, "push", "-q", "origin", "HEAD:main")
        r, out = self.run_script()
        self.assertEqual(r.returncode, 3)
        self.assertIn("push skipped: behind origin/main", r.stdout)
        self.assertEqual((out["committed"], out["pushed"]), (True, False))
        self.assertNotIn("briefs/latest.md", self.origin_files())

    def test_no_change_gives_committed_false(self):
        self.run_script()
        before = git(self.clone, "rev-parse", "HEAD")
        r, out = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (False, False))
        self.assertIn("nothing changed", r.stdout)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), before)

    def test_push_failure_exits_4(self):
        git(self.clone, "remote", "set-url", "--push", "origin", str(self.origin.parent / "missing.git"))
        r, out = self.run_script()
        self.assertEqual(r.returncode, 4)
        self.assertEqual((out["committed"], out["pushed"]), (True, False))

    def test_bad_date_exits_1(self):
        r, out = self.run_script(date="8 Oct")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(out["committed"])


if __name__ == "__main__":
    unittest.main()
