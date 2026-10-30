"""Tests for docs_drift.py. Made-up data only."""
import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "docs_drift.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "docs-drift"
sys.path.insert(0, str(SCRIPT.parent))
import docs_drift  # noqa: E402

TODAY = "2026-10-29"
WANTED = {"Features": "features", "Appearance": "appearance", "Hidden": "hidden"}

DRAFTS_YAML = """  drafts:
    - title: Customise the SDK
      file: docs/guides/fake-customise.md
      branch: docs/fake-customise
      waiting_on: design review
      added: 2026-10-20
    - title: Second page
      file: docs/guides/fake-second.md
      branch: docs/fake-second
      added: 2026-10-27
"""

CONFIG_YAML = """
docs_drift:
  lookback_days: 30
  docs_repo: example-org/fake-docs
  docs_checkout: /nowhere/fake-docs
  live_base: https://docs.example.test/v3/docs/
  watch:
    - repo: fake-sdk
      file: app/types/init.types.ts
      guide: docs/guides/fake-sdk.md
      interfaces:
        Features: features
        Appearance: appearance
        Hidden: hidden
"""

GUIDE = (FIX / "guide.md").read_text()
LIVE = (FIX / "live.html").read_text()
BEFORE = (FIX / "types_before.ts").read_text()
AFTER = (FIX / "types_after.ts").read_text()

ROUNDUP_CODE_LINE = "    roundUp?: boolean            // default: true\n"
ROUNDUP_BULLET = "  * `roundUp`: boolean. Rounds the basket up.\n"
ROUNDUP_LI = "<li><code>roundUp</code>: boolean</li>"


def without_roundup_source(text):
    assert ROUNDUP_CODE_LINE in text and ROUNDUP_BULLET in text
    return text.replace(ROUNDUP_CODE_LINE, "").replace(ROUNDUP_BULLET, "")


def without_roundup_live(text):
    assert ROUNDUP_LI in text
    return text.replace(ROUNDUP_CODE_LINE, "").replace(ROUNDUP_LI, "")


def pr(number=7, files=None, merged="2026-10-21T10:00:00Z", repo="fake-sdk"):
    return {"repo": repo, "number": number, "title": "Tidy options", "url": f"https://github.com/ekko-enviroconomy/{repo}/pull/{number}",
            "mergedAt": merged, "files": files if files is not None else ["app/types/init.types.ts", "README.md"]}


class Env:
    """Run main() with git, gh and the network patched."""

    def __init__(self, test, guide=GUIDE, live=LIVE, before=BEFORE, after=AFTER, merged=None, state=None, config=CONFIG_YAML, on_main=False):
        self.tmp = Path(tempfile.mkdtemp())
        test.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.cfg = self.tmp / "config.yaml"
        self.cfg.write_text(config)
        self.merged = self.tmp / "merged.json"
        self.merged.write_text(json.dumps([pr()] if merged is None else merged))
        self.state = self.tmp / "state.json"
        if state is not None:
            self.state.write_text(json.dumps(state))
        self.guide, self.live, self.before, self.after = guide, live, before, after
        self.on_main = on_main  # bool, or a callable (checkout, file) -> bool that may raise

    def gh_file(self, repo, path, sha):
        return self.before if sha == "base-sha" else self.after

    def fetch_live(self, url):
        if isinstance(self.live, Exception):
            raise self.live
        return self.live

    def git_on_main(self, checkout, file):
        return self.on_main(checkout, file) if callable(self.on_main) else self.on_main

    def run(self, today=TODAY):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(docs_drift, "git_fetch"), \
                mock.patch.object(docs_drift, "git_show", lambda c, g: self.guide), \
                mock.patch.object(docs_drift, "git_on_main", self.git_on_main), \
                mock.patch.object(docs_drift, "gh_pr_shas", lambda r, n: ("base-sha", "merge-sha")), \
                mock.patch.object(docs_drift, "gh_file_at", self.gh_file), \
                mock.patch.object(docs_drift, "fetch_live", self.fetch_live), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docs_drift.main(["--config", str(self.cfg), "--merged", str(self.merged),
                                    "--state", str(self.state), "--today", today])
        return code, json.loads(out.getvalue()), err.getvalue()

    def saved(self):
        return json.loads(self.state.read_text())


def by_path(items, path, change=None):
    return [i for i in items if i["path"] == path and (change is None or i["change"] == change)]


class ParserTests(unittest.TestCase):
    def test_code_block_nested_path_and_line(self):
        paths = docs_drift.parse_markdown(GUIDE)
        self.assertEqual(paths["features.roundUp"], 9)  # first appearance, in the code block
        self.assertIn("features.legacyToggle", paths)
        self.assertIn("appearance.theme", paths)
        self.assertIn("features", paths)

    def test_nested_bullet_path(self):
        text = "* `features`. Flags\n  * `roundUp`: boolean\n    * `deep`: x\n* `other`. y\n  * `roundUp`: z\n"
        paths = docs_drift.parse_markdown(text)
        self.assertEqual(paths["features.roundUp"], 2)
        self.assertEqual(paths["features.roundUp.deep"], 3)
        self.assertEqual(paths["other.roundUp"], 5)

    def test_decoys_do_not_match(self):
        paths = docs_drift.parse_markdown(GUIDE)
        # `roundUp: { amounts }` under ToggleState is a different path, the quoted union is just the leaf `key`
        self.assertIn("roundUp", paths)
        self.assertNotIn("features.amounts", paths)
        self.assertIn("key", paths)
        self.assertNotIn("carbonCredits", paths)
        self.assertNotIn("features.carbonCredits", paths)

    def test_prose_mention_ignored(self):
        self.assertNotIn("roundUp", docs_drift.parse_markdown("Prose about `roundUp` here.\n"))

    def test_interfaces_direct_members_only(self):
        got = docs_drift.parse_interfaces(BEFORE, WANTED)
        self.assertEqual(got["Features"], {"features.roundUp", "features.carbonCredits", "features.legacyToggle", "features.nested"})
        self.assertEqual(got["Appearance"], {"appearance.theme"})
        self.assertNotIn("NotWatched", got)

    def test_live_page(self):
        paths = docs_drift.parse_live(LIVE)
        self.assertEqual({"features", "features.roundUp", "features.legacyToggle", "roundUp", "key"} - paths, set())
        self.assertNotIn("carbonCredits", paths)


class DriftTests(unittest.TestCase):
    def test_removed_stale(self):
        code, items, _ = Env(self).run()
        self.assertEqual(code, 0)
        [item] = by_path(items, "features.roundUp", "removed")
        self.assertEqual(item["status"], "stale")
        self.assertEqual(item["doc"]["line"], 9)
        self.assertEqual(item["doc"]["url"], "https://github.com/example-org/fake-docs/blob/main/docs/guides/fake-sdk.md#L9")
        self.assertEqual(item["live_url"], "https://docs.example.test/v3/docs/fake-sdk")
        self.assertEqual(item["pr"], {"repo": "fake-sdk", "number": 7, "url": "https://github.com/ekko-enviroconomy/fake-sdk/pull/7", "merged": "2026-10-21"})
        self.assertEqual(list(item), ["path", "change", "pr", "doc", "live_url", "status", "live_checked", "first_seen", "age_days"])
        self.assertTrue(item["live_checked"])
        self.assertEqual((item["first_seen"], item["age_days"]), ("2026-10-21", 8))  # merge date, not today
        self.assertEqual(by_path(items, "features.carbonCredits"), [])

    def test_removed_upload_pending(self):
        _, items, _ = Env(self, guide=without_roundup_source(GUIDE)).run()
        [item] = by_path(items, "features.roundUp", "removed")
        self.assertEqual(item["status"], "upload_pending")
        self.assertIsNone(item["doc"]["line"])
        self.assertEqual(item["doc"]["url"], "https://github.com/example-org/fake-docs/blob/main/docs/guides/fake-sdk.md")

    def test_removed_fixed_everywhere_no_item(self):
        _, items, _ = Env(self, guide=without_roundup_source(GUIDE), live=without_roundup_live(LIVE)).run()
        self.assertEqual(by_path(items, "features.roundUp"), [])

    def test_added_stale_when_parent_documented(self):
        _, items, _ = Env(self).run()
        [item] = by_path(items, "features.extraOption", "added")
        self.assertEqual(item["status"], "stale")
        self.assertIsNone(item["doc"]["line"])

    def test_added_upload_pending(self):
        guide = GUIDE.replace("    legacyToggle?: boolean\n  }\n  appearance", "    legacyToggle?: boolean\n    extraOption?: string\n  }\n  appearance")
        self.assertNotEqual(guide, GUIDE)
        _, items, _ = Env(self, guide=guide).run()
        [item] = by_path(items, "features.extraOption", "added")
        self.assertEqual(item["status"], "upload_pending")
        self.assertIsNotNone(item["doc"]["line"])

    def test_added_documented_in_both_no_item(self):
        guide = GUIDE.replace("    legacyToggle?: boolean\n  }\n  appearance", "    legacyToggle?: boolean\n    extraOption?: string\n  }\n  appearance")
        live = LIVE.replace("    legacyToggle?: boolean\n", "    legacyToggle?: boolean\n    extraOption?: string\n")
        _, items, _ = Env(self, guide=guide, live=live).run()
        self.assertEqual(by_path(items, "features.extraOption"), [])

    def test_added_with_undocumented_parent_ignored(self):
        _, items, _ = Env(self).run()
        self.assertEqual(by_path(items, "hidden.foo"), [])
        self.assertEqual(by_path(items, "notWatched.yyy"), [])

    def test_live_fetch_failure(self):
        env = Env(self, live=OSError("boom"))
        _, items, err = env.run()
        self.assertIn("warning:", err)
        [item] = by_path(items, "features.roundUp", "removed")
        self.assertEqual((item["status"], item["live_checked"]), ("stale", False))
        # source says fixed and live is unknown: nothing to report
        _, items, _ = Env(self, guide=without_roundup_source(GUIDE), live=OSError("boom")).run()
        self.assertEqual(by_path(items, "features.roundUp"), [])

    def test_file_not_touched_or_outside_window_skipped(self):
        _, items, _ = Env(self, merged=[pr(files=["README.md"])]).run()
        self.assertEqual(items, [])
        _, items, _ = Env(self, merged=[pr(merged="2026-08-01T10:00:00Z")]).run()
        self.assertEqual(items, [])
        _, items, _ = Env(self, merged=[pr(repo="other-repo")]).run()
        self.assertEqual(items, [])

    def test_pr_failure_warns_and_continues(self):
        env = Env(self, merged=[pr(number=1), pr(number=2)])
        calls = []

        def shas(repo, number):
            calls.append(number)
            if number == 1:
                raise RuntimeError("gh down")
            return "base-sha", "merge-sha"

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(docs_drift, "git_fetch"), \
                mock.patch.object(docs_drift, "git_show", lambda c, g: GUIDE), \
                mock.patch.object(docs_drift, "gh_pr_shas", shas), \
                mock.patch.object(docs_drift, "gh_file_at", env.gh_file), \
                mock.patch.object(docs_drift, "fetch_live", env.fetch_live), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docs_drift.main(["--config", str(env.cfg), "--merged", str(env.merged),
                                    "--state", str(env.state), "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("warning:", err.getvalue())
        self.assertEqual({i["pr"]["number"] for i in json.loads(out.getvalue())}, {2})


class StateTests(unittest.TestCase):
    def test_first_seen_is_merge_date_then_stored_value_wins(self):
        env = Env(self)
        env.run(today="2026-10-22")
        saved = env.saved()
        self.assertEqual(saved["updated"], "2026-10-22")
        key = "features.roundUp|removed|fake-sdk#7"
        self.assertEqual(saved["items"][key]["first_seen"], "2026-10-21")
        self.assertEqual(saved["items"][key]["age_days"], 1)
        # a stored first_seen wins over the merge date, and the key is not duplicated
        saved["items"][key]["first_seen"] = "2026-10-25"
        env.state.write_text(json.dumps(saved))
        _, items, _ = env.run(today=TODAY)
        [item] = by_path(items, "features.roundUp", "removed")
        self.assertEqual((item["first_seen"], item["age_days"]), ("2026-10-25", 4))

    def test_stored_item_kept_without_pr_and_status_updated(self):
        env = Env(self)
        env.run(today="2026-10-22")
        env.merged.write_text("[]")
        env.guide = without_roundup_source(GUIDE)
        _, items, _ = env.run()
        [item] = by_path(items, "features.roundUp", "removed")
        self.assertEqual((item["status"], item["age_days"]), ("upload_pending", 8))  # first_seen = merge date 21 Oct
        self.assertIsNone(item["doc"]["line"])

    def test_dropped_when_fixed(self):
        env = Env(self)
        env.run(today="2026-10-22")
        env.merged.write_text("[]")
        env.guide, env.live = without_roundup_source(GUIDE), without_roundup_live(LIVE)
        _, items, _ = env.run()
        self.assertEqual(by_path(items, "features.roundUp"), [])
        self.assertNotIn("features.roundUp|removed|fake-sdk#7", env.saved()["items"])

    def test_sorted_by_age_then_path(self):
        env = Env(self, merged=[])
        old = {"path": "features.zzz", "change": "removed", "pr": {"repo": "fake-sdk", "number": 1, "url": "u", "merged": "2026-10-01"},
               "doc": {"file": "docs/guides/fake-sdk.md", "line": 3, "url": "x"}, "live_url": "l", "status": "stale",
               "live_checked": True, "first_seen": "2026-10-10", "age_days": 0}
        guide = GUIDE + "\n```ts\nx = {\n  features: {\n    zzz: 1\n  }\n}\n```\n"
        env.guide = guide
        env.state.write_text(json.dumps({"items": {"features.zzz|removed|fake-sdk#1": old}, "updated": "2026-10-10"}))
        env.merged.write_text(json.dumps([pr()]))
        _, items, _ = env.run()
        self.assertEqual(items[0]["path"], "features.zzz")
        self.assertEqual(items[0]["age_days"], 19)
        self.assertEqual([i["age_days"] for i in items][1:], [8] * (len(items) - 1))  # new items age from the merge date

    def test_empty_state_file(self):
        env = Env(self)
        env.state.write_text("")
        _, items, _ = env.run()
        self.assertTrue(items)


class DraftTests(unittest.TestCase):
    CONFIG = CONFIG_YAML + DRAFTS_YAML

    def drafts(self, items):
        return [i for i in items if i["status"] == "draft"]

    def test_draft_emitted_after_code_drift(self):
        _, items, _ = Env(self, config=self.CONFIG).run()
        drafts = self.drafts(items)
        self.assertEqual(items[-2:], drafts)  # config order, after every code-drift item
        self.assertTrue(len(items) > 2)
        self.assertEqual(drafts[0], {
            "status": "draft", "title": "Customise the SDK", "branch": "docs/fake-customise",
            "waiting_on": "design review",
            "doc": {"file": "docs/guides/fake-customise.md", "line": None,
                    "url": "https://github.com/example-org/fake-docs/blob/docs/fake-customise/docs/guides/fake-customise.md"},
            "first_seen": "2026-10-20", "age_days": 9})
        self.assertIsNone(drafts[1]["waiting_on"])
        self.assertEqual(drafts[1]["age_days"], 2)

    def test_draft_dropped_when_file_on_main(self):
        on_main = lambda c, f: f == "docs/guides/fake-customise.md"
        _, items, _ = Env(self, config=self.CONFIG, on_main=on_main).run()
        self.assertEqual([i["title"] for i in self.drafts(items)], ["Second page"])
        _, items, _ = Env(self, config=self.CONFIG, on_main=True).run()
        self.assertEqual(self.drafts(items), [])

    def test_draft_kept_when_git_check_errors(self):
        def boom(c, f):
            raise RuntimeError("git failed")
        _, items, err = Env(self, config=self.CONFIG, on_main=boom).run()
        self.assertEqual(len(self.drafts(items)), 2)
        self.assertIn("warning:", err)

    def test_drafts_not_written_to_state(self):
        env = Env(self, config=self.CONFIG)
        env.run()
        self.assertFalse([k for k, v in env.saved()["items"].items() if v.get("status") == "draft"])
        self.assertNotIn("Customise the SDK", json.dumps(env.saved()))

    def test_drafts_only_config_without_merged_prs(self):
        _, items, _ = Env(self, config=self.CONFIG, merged=[]).run()
        self.assertEqual(len(items), 2)
        self.assertEqual({i["status"] for i in items}, {"draft"})

    def test_bad_draft_config_exits_1(self):
        for bad in ("  drafts:\n    - title: T\n      file: f.md\n      branch: b\n",
                    "  drafts:\n    - title: T\n      file: f.md\n      branch: b\n      added: soon\n",
                    "  drafts: nope\n"):
            env = Env(self, config=CONFIG_YAML + bad)
            with contextlib.redirect_stderr(io.StringIO()):
                code = docs_drift.main(["--config", str(env.cfg), "--merged", str(env.merged),
                                        "--state", str(env.state), "--today", TODAY])
            self.assertEqual(code, 1)


class GitOnMainTests(unittest.TestCase):
    def check(self, message):
        with mock.patch.object(docs_drift, "run_cmd", side_effect=RuntimeError(message)):
            return docs_drift.git_on_main("/x", "f.md")

    def test_missing_file_is_false_and_other_errors_raise(self):
        self.assertFalse(self.check("git -C /x cat-file failed: fatal: path 'f.md' does not exist in 'origin/main'"))
        with self.assertRaises(RuntimeError):
            self.check("git -C /x cat-file failed: fatal: invalid object name 'origin/main'.")
        with mock.patch.object(docs_drift, "run_cmd", return_value=""):
            self.assertTrue(docs_drift.git_on_main("/x", "f.md"))


class ConfigTests(unittest.TestCase):
    def test_missing_block_prints_empty_list(self):
        env = Env(self, config="other_key: 1\n")
        code, items, err = env.run()
        self.assertEqual((code, items), (0, []))
        self.assertTrue(err.strip())
        self.assertFalse(env.state.exists())

    def test_bad_today(self):
        env = Env(self)
        with contextlib.redirect_stderr(io.StringIO()):
            code = docs_drift.main(["--config", str(env.cfg), "--merged", str(env.merged),
                                    "--state", str(env.state), "--today", "nope"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
