"""Tests for waiting_age.py. Made-up data only."""
import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "waiting_age.py"
sys.path.insert(0, str(SCRIPT.parent))
import waiting_age  # noqa: E402

TODAY = "2026-10-27"

MILESTONES_MD = """# Milestones

```yaml
milestones:
  - id: acme-kickoff
    name: Acme kick-off
    date:
    kind: go-live
    client: Acme
    projects: [client-acme]
    gates:
      - Staging access issued
      - 'Lena''s copy: taken on 28 Aug, never produced'
      - 'Slipped past 2026-09-11. No new date'
    status: at-risk
  - id: beta-launch
    name: Beta launch
    date: 2026-12-31
    kind: launch
    client: Beta
    projects:
      - client-beta
      - project-shared
    gates: []
    status: on-track
  - id: gamma-live
    name: Gamma live
    date:
    kind: go-live
    client: Gamma
    projects: [client-gamma]
    gates:
      - Date from Gamma
    status: on-track
  - id: delta-off
    name: Delta turned off
    date: 2026-11-01
    kind: internal
    client: Delta
    projects: [client-delta]
    gates: []
    status: done
```
"""


def notion(id_="n1", text="Sign-off on copy", **kw):
    return {"kind": "notion", "id": id_, "text": text, **kw}


def fathom(key="f1", text="Send the deck", **kw):
    return {"kind": "fathom", "key": key, "text": text, **kw}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.briefs = self.dir / "briefs"
        self.briefs.mkdir()
        self.milestones = self.dir / "milestones.md"
        self.milestones.write_text(MILESTONES_MD, encoding="utf-8")
        self.chased = self.dir / "chased.json"

    def brief(self, date, data):
        (self.briefs / f"{date}.json").write_text(json.dumps(data), encoding="utf-8")

    def run_cli(self, items, today=TODAY, raw=None):
        path = self.dir / "items.json"
        path.write_text(raw if raw is not None else json.dumps(items), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--items", str(path), "--briefs-dir", str(self.briefs),
             "--milestones", str(self.milestones), "--chased", str(self.chased), "--today", today],
            capture_output=True, text=True)

    def run_ok(self, items, today=TODAY):
        r = self.run_cli(items, today)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def one(self, item, today=TODAY):
        return self.run_ok([item], today)[0]


class SinceTest(Base):
    def test_fathom_uses_meeting_date(self):
        self.brief("2026-10-01", {"actions": {"product": [{"key": "f1"}]}})
        r = self.one(fathom(meeting_date="2026-10-20"))
        self.assertEqual((r["since"], r["days"]), ("2026-10-20", 7))

    def test_since_from_past_waiting_entry_by_id_earliest_wins(self):
        self.brief("2026-10-10", {"waiting": [{"kind": "notion", "id": "n1"}]})
        self.brief("2026-10-20", {"waiting": [{"kind": "notion", "id": "n1"}]})
        self.brief("2026-10-15", {"waiting": [{"kind": "notion", "id": "other"}]})
        r = self.one(notion())
        self.assertEqual((r["since"], r["days"]), ("2026-10-10", 17))

    def test_waiting_entry_needs_same_kind(self):
        self.brief("2026-10-10", {"waiting": [{"kind": "fathom", "id": "n1", "key": "zzz"}]})
        self.assertEqual(self.one(notion())["since"], TODAY)

    def test_fathom_since_from_past_waiting_by_key(self):
        self.brief("2026-10-12", {"waiting": [{"kind": "fathom", "key": "f1"}]})
        self.assertEqual(self.one(fathom())["since"], "2026-10-12")

    def test_since_from_old_format_waiting_on_text(self):
        self.brief("2026-10-05", {"projects": [{"name": "P", "waiting_on": [{"text": "  sign-off   ON copy "}]}]})
        r = self.one(notion())
        self.assertEqual((r["since"], r["days"]), ("2026-10-05", 22))

    def test_old_format_waiting_on_plain_strings(self):
        self.brief("2026-10-05", {"projects": [{"waiting_on": ["Sign-off on copy"]}]})
        self.assertEqual(self.one(notion())["since"], "2026-10-05")

    def test_old_format_text_not_used_for_fathom(self):
        self.brief("2026-10-05", {"projects": [{"waiting_on": [{"text": "Send the deck"}]}]})
        self.assertEqual(self.one(fathom())["since"], TODAY)

    def test_since_from_old_actions_product_key(self):
        self.brief("2026-10-08", {"actions": {"product": [{"key": "f1", "text": "x"}]}})
        self.assertEqual(self.one(fathom())["since"], "2026-10-08")

    def test_fallback_is_today(self):
        r = self.one(notion())
        self.assertEqual((r["since"], r["days"]), (TODAY, 0))

    def test_briefs_dated_today_or_later_ignored(self):
        self.brief(TODAY, {"waiting": [{"kind": "notion", "id": "n1"}]})
        self.brief("2026-10-28", {"waiting": [{"kind": "notion", "id": "n1"}]})
        self.assertEqual(self.one(notion())["since"], TODAY)

    def test_unreadable_briefs_and_other_files_skipped(self):
        (self.briefs / "2026-10-01.json").write_text("not json")
        (self.briefs / "2026-10-02.json").write_text("[1, 2]")
        (self.briefs / "latest.md").write_text("x")
        self.brief("2026-10-03", {"waiting": "oops", "projects": "oops", "actions": []})
        self.brief("2026-10-04", {"waiting": [{"kind": "notion", "id": "n1"}]})
        self.assertEqual(self.one(notion())["since"], "2026-10-04")

    def test_missing_briefs_dir(self):
        self.briefs.rmdir()
        self.assertEqual(self.one(notion())["since"], TODAY)


class ChaseReasonTest(Base):
    def waiting_since(self, days, id_="n1"):
        d = dt.date.fromisoformat(TODAY) - dt.timedelta(days=days)
        self.brief(d.isoformat(), {"waiting": [{"kind": "notion", "id": id_}]})

    def test_gate_at_three_days_at_risk_without_date(self):
        self.waiting_since(3)
        r = self.one(notion(project_slug="client-acme"))
        self.assertEqual(r["chase_reason"], "gates Acme kick-off")
        self.assertEqual(r["gates"], "Acme kick-off")
        self.assertTrue(r["chase"])

    def test_gated_at_two_days_is_null_but_gates_set(self):
        self.waiting_since(2)
        r = self.one(notion(project_slug="client-acme"))
        self.assertEqual((r["chase_reason"], r["chase"], r["gates"]), (None, False, "Acme kick-off"))

    def test_gate_with_date_block_list_projects(self):
        self.waiting_since(4)
        r = self.one(notion(project_slug="project-shared"))
        self.assertEqual(r["chase_reason"], "gates Beta launch")

    def test_on_track_without_date_does_not_gate(self):
        self.waiting_since(5)
        r = self.one(notion(project_slug="client-gamma"))
        self.assertEqual((r["chase_reason"], r["gates"]), (None, None))

    def test_done_milestone_does_not_gate(self):
        self.waiting_since(5)
        r = self.one(notion(project_slug="client-delta"))
        self.assertEqual((r["chase_reason"], r["gates"]), (None, None))

    def test_unknown_or_missing_slug(self):
        self.waiting_since(5)
        self.assertIsNone(self.one(notion(project_slug="nope"))["chase_reason"])
        r = self.one(notion())
        self.assertEqual((r["chase_reason"], r["gates"]), (None, None))

    def test_missing_milestones_file(self):
        self.milestones.unlink()
        self.waiting_since(5)
        r = self.one(notion(project_slug="client-acme"))
        self.assertEqual((r["chase_reason"], r["gates"]), (None, None))

    def test_due_today_or_earlier(self):
        r = self.one(notion(due="2026-10-27"))
        self.assertEqual(r["chase_reason"], "chase-by date 27 Oct")
        r = self.one(notion(due="2026-03-05"))
        self.assertEqual(r["chase_reason"], "chase-by date 5 Mar")

    def test_due_in_future_is_no_reason(self):
        self.assertIsNone(self.one(notion(due="2026-10-28"))["chase_reason"])

    def test_waiting_seven_days(self):
        self.waiting_since(7)
        r = self.one(notion())
        self.assertEqual((r["chase_reason"], r["chase"]), ("waiting 7 days", True))

    def test_six_days_is_no_reason(self):
        self.waiting_since(6)
        r = self.one(notion())
        self.assertEqual((r["chase_reason"], r["chase"]), (None, False))

    def test_gated_old_item_keeps_gate_wording(self):
        self.waiting_since(10)
        r = self.one(notion(project_slug="client-acme"))
        self.assertEqual(r["chase_reason"], "gates Acme kick-off")

    def test_precedence_due_then_gate_then_age(self):
        self.waiting_since(26)
        item = notion(project_slug="client-acme", due="2026-10-01")
        self.assertEqual(self.one(item)["chase_reason"], "chase-by date 1 Oct")
        item = notion(project_slug="client-acme")
        self.assertEqual(self.one(item)["chase_reason"], "gates Acme kick-off")
        self.assertEqual(self.one(notion())["chase_reason"], "waiting 26 days")


class ChasedTest(Base):
    def chased_days_ago(self, n, key="notion:n1"):
        d = dt.date.fromisoformat(TODAY) - dt.timedelta(days=n)
        self.chased.write_text(json.dumps({key: d.isoformat()}))

    def test_chased_six_days_ago_suppresses_chase_keeps_reason(self):
        self.chased_days_ago(6)
        r = self.one(notion(project_slug="client-acme", due="2026-10-01"))
        self.assertEqual(r["chased_on"], "2026-10-21")
        self.assertEqual(r["chase_reason"], "chase-by date 1 Oct")
        self.assertFalse(r["chase"])

    def test_chased_seven_days_ago_chases_again(self):
        self.chased_days_ago(7)
        self.assertTrue(self.one(notion(project_slug="client-acme", due="2026-10-01"))["chase"])

    def test_fathom_key_lookup(self):
        self.chased_days_ago(1, "fathom:f1")
        self.assertEqual(self.one(fathom())["chased_on"], "2026-10-26")

    def test_absent_is_null(self):
        self.assertIsNone(self.one(notion())["chased_on"])

    def test_malformed_chased_counts_as_empty(self):
        for raw in ("not json", "[1]", json.dumps({"notion:n1": "garbage"})):
            self.chased.write_text(raw)
            self.assertIsNone(self.one(notion())["chased_on"])

    def test_chased_without_reason_stays_false(self):
        self.chased_days_ago(30)
        r = self.one(notion())
        self.assertEqual((r["chase_reason"], r["chase"]), (None, False))


class OutputTest(Base):
    def test_shape_and_passthrough(self):
        item = notion(who="Simon", url="https://x.test/1", project="Acme", project_slug="client-acme",
                      due="2026-11-30", extra={"a": 1})
        r = self.one(item)
        self.assertEqual(r, {
            "kind": "notion", "id": "n1", "text": "Sign-off on copy", "who": "Simon", "url": "https://x.test/1",
            "project": "Acme", "project_slug": "client-acme", "due": "2026-11-30", "extra": {"a": 1},
            "since": TODAY, "days": 0, "chased_on": None, "gates": "Acme kick-off", "chase_reason": None,
            "chase": False,
        })

    def test_sort_chase_first_then_days_desc_then_text(self):
        self.brief("2026-10-10", {"waiting": [{"kind": "notion", "id": "old"}, {"kind": "notion", "id": "mid"}]})
        self.brief("2026-10-24", {"waiting": [{"kind": "notion", "id": "recent"}]})
        self.chased.write_text(json.dumps({"notion:mid": "2026-10-26"}))
        items = [
            notion("recent", "Recent, no reason"),
            notion("mid", "Mid, chased yesterday"),   # 17 days but chase false
            notion("b", "B due", due="2026-10-01"),   # chase, 0 days
            notion("old", "Old, waiting"),            # chase, 17 days
            notion("a", "A due", due="2026-10-02"),   # chase, 0 days
        ]
        got = [r["id"] for r in self.run_ok(items)]
        self.assertEqual(got, ["old", "a", "b", "mid", "recent"])

    def test_empty_list(self):
        self.assertEqual(self.run_ok([]), [])


class InvalidInputTest(Base):
    def assert_fails(self, items=None, raw=None):
        r = self.run_cli(items, raw=raw)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.strip())
        self.assertEqual(r.stdout, "")

    def test_bad_json(self):
        self.assert_fails(raw="{nope")

    def test_not_a_list(self):
        self.assert_fails({"kind": "notion"})

    def test_missing_kind(self):
        self.assert_fails([{"id": "n1", "text": "x"}])

    def test_bad_kind(self):
        self.assert_fails([{"kind": "slack", "id": "n1", "text": "x"}])

    def test_notion_missing_id(self):
        self.assert_fails([{"kind": "notion", "key": "k", "text": "x"}])

    def test_fathom_missing_key(self):
        self.assert_fails([{"kind": "fathom", "id": "n1", "text": "x"}])

    def test_missing_or_empty_text(self):
        self.assert_fails([{"kind": "notion", "id": "n1"}])
        self.assert_fails([{"kind": "notion", "id": "n1", "text": "  "}])

    def test_missing_items_file(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--items", str(self.dir / "nope.json"),
                            "--briefs-dir", str(self.briefs), "--milestones", str(self.milestones),
                            "--chased", str(self.chased), "--today", TODAY], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


class MilestoneParserTest(unittest.TestCase):
    def test_parses_entries(self):
        ms = waiting_age.parse_milestones(MILESTONES_MD)
        self.assertEqual([m["id"] for m in ms], ["acme-kickoff", "beta-launch", "gamma-live", "delta-off"])
        acme = ms[0]
        self.assertEqual(acme["name"], "Acme kick-off")
        self.assertEqual(acme["date"], "")
        self.assertEqual(acme["projects"], ["client-acme"])
        self.assertEqual(acme["status"], "at-risk")
        self.assertEqual(acme["gates"], ["Staging access issued", "Lena's copy: taken on 28 Aug, never produced",
                                         "Slipped past 2026-09-11. No new date"])

    def test_block_and_empty_lists_and_dates(self):
        ms = waiting_age.parse_milestones(MILESTONES_MD)
        self.assertEqual(ms[1]["projects"], ["client-beta", "project-shared"])
        self.assertEqual(ms[1]["gates"], [])
        self.assertEqual(ms[1]["date"], "2026-12-31")

    def test_frontmatter_format(self):
        text = "---\nmilestones:\n  - id: x\n    name: X\n    projects: [a, b]\n    status: at-risk\n---\n# Doc\n"
        self.assertEqual(waiting_age.parse_milestones(text),
                         [{"id": "x", "name": "X", "projects": ["a", "b"], "status": "at-risk"}])

    def test_frontmatter_wins_over_body_fence(self):
        text = ("---\nmilestones:\n  - id: x\n    name: X\n    status: at-risk\n---\n# Doc\n"
                "```yaml\nmilestones:\n  - id: wrong\n    name: Wrong\n```\n")
        self.assertEqual([m["id"] for m in waiting_age.parse_milestones(text)], ["x"])

    def test_fence_used_when_no_frontmatter(self):
        text = "# Doc\n```yaml\nmilestones:\n  - id: f\n    name: F\n```\n"
        self.assertEqual([m["id"] for m in waiting_age.parse_milestones(text)], ["f"])

    def test_inline_comment_stripped_from_scalars(self):
        text = ("---\nmilestones:\n  - id: x  # first\n    name: 'A # B'  # keep hash in quotes\n"
                "    status: done  # shipped\n---\n")
        ms = waiting_age.parse_milestones(text)
        self.assertEqual((ms[0]["id"], ms[0]["name"], ms[0]["status"]), ("x", "A # B", "done"))

    def test_scalar_projects_is_one_item_list_exact_match(self):
        ms = waiting_age.parse_milestones(
            "---\nmilestones:\n  - id: x\n    name: X\n    projects: client-acme\n    status: at-risk\n---\n")
        self.assertEqual(waiting_age.gating_milestone("client-acme", ms), "X")
        self.assertIsNone(waiting_age.gating_milestone("client", ms))
        self.assertIsNone(waiting_age.gating_milestone("acme", ms))

    def test_no_block(self):
        self.assertEqual(waiting_age.parse_milestones("# nothing here"), [])


if __name__ == "__main__":
    unittest.main()
