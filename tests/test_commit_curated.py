import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "commit_curated.sh"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": "/dev/null"}


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class CommitCuratedTest(unittest.TestCase):
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
        (self.clone / "projects").mkdir()
        (self.clone / "briefs").mkdir()
        (self.clone / "README.md").write_text("product-os\n")
        (self.clone / "notes.md").write_text("notes\n")
        (self.clone / "projects" / "alpha.md").write_text("alpha\n")
        (self.clone / "briefs" / "latest.md").write_text("brief\n")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "init")
        git(self.clone, "push", "-q", "origin", "HEAD:main")

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, *args, message="update"):
        r = subprocess.run(["bash", str(SCRIPT), str(self.clone), message, *args],
                           capture_output=True, text=True, env=ENV)
        last = r.stdout.strip().splitlines()[-1]
        return r, json.loads(last)

    def push_upstream_change(self, name="README.md", text="changed upstream\n"):
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.other)], check=True, env=ENV,
                       capture_output=True)
        (self.other / name).write_text(text)
        git(self.other, "add", name)
        git(self.other, "commit", "-q", "-m", "upstream")
        git(self.other, "push", "-q", "origin", "HEAD:main")

    def assert_refused(self, *args):
        before = git(self.clone, "rev-parse", "HEAD")
        r, out = self.run_script(*args)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (False, False))
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), before)
        self.assertEqual(git(self.origin, "rev-parse", "main"), before)

    def test_commits_only_named_files_and_pushes(self):
        (self.clone / "projects" / "alpha.md").write_text("alpha v2\n")
        (self.clone / "projects" / "new.md").write_text("new\n")
        r, out = self.run_script("projects/alpha.md", "projects/new.md", message="accept project updates")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (True, True))
        changed = git(self.clone, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertEqual(sorted(changed), ["projects/alpha.md", "projects/new.md"])
        self.assertEqual(git(self.origin, "log", "-1", "--format=%s", "main"), "accept project updates")
        self.assertEqual(git(self.origin, "show", "main:projects/alpha.md"), "alpha v2")

    def test_unrelated_changes_survive_untouched(self):
        (self.clone / "notes.md").write_text("staged edit\n")
        git(self.clone, "add", "notes.md")
        (self.clone / "README.md").write_text("unstaged edit\n")
        (self.clone / "scratch.md").write_text("untracked\n")
        (self.clone / "projects" / "alpha.md").write_text("alpha v2\n")
        r, out = self.run_script("projects/alpha.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out["pushed"])
        changed = git(self.clone, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertEqual(changed, ["projects/alpha.md"])
        status = git(self.clone, "status", "--porcelain")
        self.assertIn("M  notes.md", status)
        self.assertIn("M README.md", status.splitlines()[0])  # unstaged; git() strips the leading space
        self.assertIn("?? scratch.md", status)
        self.assertEqual((self.clone / "README.md").read_text(), "unstaged edit\n")
        self.assertEqual(git(self.origin, "show", "main:notes.md"), "notes")

    def test_tracked_deletion_is_committed(self):
        (self.clone / "projects" / "alpha.md").unlink()
        r, out = self.run_script("projects/alpha.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (True, True))
        self.assertNotIn("projects/alpha.md", git(self.origin, "ls-tree", "-r", "--name-only", "main"))

    def test_briefs_path_refused(self):
        (self.clone / "briefs" / "latest.md").write_text("edited\n")
        self.assert_refused("briefs/latest.md")
        self.assert_refused("./briefs/latest.md")
        self.assert_refused("projects/alpha.md", "briefs/latest.md")

    def test_dotdot_and_absolute_paths_refused(self):
        self.assert_refused("../outside.md")
        self.assert_refused("projects/../notes.md")
        self.assert_refused(str(self.clone / "notes.md"))

    def test_missing_path_refused(self):
        self.assert_refused("projects/nope.md")

    def test_too_few_args_refused(self):
        r = subprocess.run(["bash", str(SCRIPT), str(self.clone), "msg"], capture_output=True, text=True, env=ENV)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout.strip().splitlines()[-1])["committed"])

    def test_not_a_git_repo_refused(self):
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        r = subprocess.run(["bash", str(SCRIPT), str(plain), "msg", "x.md"], capture_output=True, text=True, env=ENV)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["reason"], "not a git repo")

    def test_not_on_main_refused(self):
        git(self.clone, "checkout", "-q", "-b", "feature/x")
        (self.clone / "notes.md").write_text("edited\n")
        before = git(self.clone, "rev-parse", "HEAD")
        r, out = self.run_script("notes.md")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(out["reason"], "not on main")
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), before)

    def test_behind_origin_fast_forwards_then_pushes(self):
        self.push_upstream_change("README.md", "changed upstream\n")
        (self.clone / "notes.md").write_text("local edit\n")
        r, out = self.run_script("notes.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (True, True))
        self.assertEqual(git(self.origin, "show", "main:README.md"), "changed upstream")
        self.assertEqual(git(self.origin, "show", "main:notes.md"), "local edit")
        self.assertEqual(git(self.origin, "rev-list", "--merges", "--count", "main"), "0")
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), git(self.origin, "rev-parse", "main"))

    def test_fast_forward_refused_exits_3(self):
        self.push_upstream_change("notes.md", "changed upstream\n")
        (self.clone / "notes.md").write_text("local edit\n")
        (self.clone / "projects" / "alpha.md").write_text("alpha v2\n")
        remote_before = git(self.origin, "rev-parse", "main")
        r, out = self.run_script("projects/alpha.md")
        self.assertEqual(r.returncode, 3)
        self.assertEqual((out["committed"], out["pushed"]), (False, False))
        self.assertEqual(out["reason"], "cannot fast-forward")
        self.assertEqual(git(self.origin, "rev-parse", "main"), remote_before)
        self.assertEqual((self.clone / "notes.md").read_text(), "local edit\n")

    def test_diverged_exits_3_and_remote_unchanged(self):
        (self.clone / "notes.md").write_text("local only\n")
        git(self.clone, "add", "notes.md")
        git(self.clone, "commit", "-q", "-m", "local commit")
        self.push_upstream_change("README.md", "changed upstream\n")
        remote_before = git(self.origin, "rev-parse", "main")
        local_before = git(self.clone, "rev-parse", "HEAD")
        (self.clone / "projects" / "alpha.md").write_text("alpha v2\n")
        r, out = self.run_script("projects/alpha.md")
        self.assertEqual(r.returncode, 3)
        self.assertFalse(out["pushed"])
        self.assertEqual(out["reason"], "diverged from origin/main")
        self.assertEqual(git(self.origin, "rev-parse", "main"), remote_before)
        self.assertEqual(git(self.clone, "rev-list", "--merges", "--count", "HEAD"), "0")
        self.assertTrue(out["committed"])
        self.assertEqual(git(self.clone, "rev-parse", "HEAD~1"), local_before)

    def test_push_failure_exits_4_and_keeps_commit(self):
        git(self.clone, "remote", "set-url", "--push", "origin", str(self.origin.parent / "missing.git"))
        (self.clone / "notes.md").write_text("local edit\n")
        r, out = self.run_script("notes.md", message="keep me")
        self.assertEqual(r.returncode, 4)
        self.assertEqual((out["committed"], out["pushed"]), (True, False))
        self.assertEqual(git(self.clone, "log", "-1", "--format=%s"), "keep me")

    def test_fetch_failure_exits_4(self):
        git(self.clone, "remote", "set-url", "origin", str(self.origin.parent / "missing.git"))
        (self.clone / "notes.md").write_text("local edit\n")
        r, out = self.run_script("notes.md")
        self.assertEqual(r.returncode, 4)
        self.assertEqual((out["committed"], out["pushed"]), (False, False))

    def test_nothing_to_commit_or_push_exits_0(self):
        before = git(self.clone, "rev-parse", "HEAD")
        r, out = self.run_script("notes.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (False, False))
        self.assertIn("nothing to push", r.stdout)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), before)

    def test_nothing_to_commit_pushes_earlier_local_commit(self):
        (self.clone / "notes.md").write_text("earlier commit\n")
        git(self.clone, "add", "notes.md")
        git(self.clone, "commit", "-q", "-m", "earlier")
        r, out = self.run_script("projects/alpha.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["committed"], out["pushed"]), (False, True))
        self.assertEqual(git(self.origin, "show", "main:notes.md"), "earlier commit")


if __name__ == "__main__":
    unittest.main()
