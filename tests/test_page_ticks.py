"""Tests for page_ticks.py. Made-up and sample data only."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "page_ticks.py"
FIXTURES = ROOT / "tests" / "fixtures" / "page-ticks"
sys.path.insert(0, str(SCRIPT.parent))
import page_ticks  # noqa: E402

NOW = "2026-10-29T08:00:00Z"
HEX_A = "a" * 32


def run_cli(docs, state, *extra):
    """Run the script; return (exit code, parsed stdout, stderr)."""
    r = subprocess.run([sys.executable, str(SCRIPT), "--docs-dir", str(docs), "--state-dir", str(state), *extra],
                       capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def fixture_out():
    code, out, _ = run_cli(FIXTURES / "docs", FIXTURES / "state", "--now", NOW)
    assert code == 0
    return out


def page(**extra):
    return {"status": "done", "by": "page", "at": "2026-10-28T09:00:00Z", **extra}


class Scratch(unittest.TestCase):
    """A temp docs dir and state dir, with helpers to fill them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.docs = Path(self._tmp.name) / "docs"
        self.state = Path(self._tmp.name) / "state"
        (self.docs / "brief-updates").mkdir(parents=True)
        self.state.mkdir()

    def doc(self, date, items, name=None):
        (self.docs / "brief-updates" / (name or f"{date}.json")).write_text(
            json.dumps({"date": date, "items": items}), encoding="utf-8")

    def numbers(self, date, numbers):
        (self.state / f"brief-map-{date}.json").write_text(
            json.dumps({"date": date, "numbers": numbers}), encoding="utf-8")

    def triage(self, date, prs):
        (self.state / f"triage-{date}.json").write_text(json.dumps({"prs": prs}), encoding="utf-8")

    def run_one(self, rec, entry, date="2026-10-28"):
        """One tick record against one map entry; return the output."""
        self.doc(date, {"1": rec})
        self.numbers(date, {"1": entry})
        return page_ticks.build(self.docs, self.state, NOW)


class PendingVsIgnoredTest(unittest.TestCase):
    def test_pending_numbers_on_the_fixture(self):
        got = [(t["date"], t["n"]) for t in fixture_out()["pending"]]
        self.assertEqual(got, [("2026-10-27", "1"), ("2026-10-27", "2"), ("2026-10-27", "3"),
                               ("2026-10-28", "1"), ("2026-10-28", "2"), ("2026-10-28", "3"),
                               ("2026-10-28", "4"), ("2026-10-28", "5"), ("2026-10-28", "18")])

    def test_ignored_records_never_appear_anywhere(self):
        out = fixture_out()
        seen = {(t["date"], t["n"]) for t in out["pending"]} | {(s["date"], s["n"]) for s in out["skipped"]}
        # 6 open, 7 started, 8 synced, 9 no by, abc/0/-1/1.5/007 bad numbers, 15 junk status, 16 string,
        # 17 by "Page", 19 by is an object, 20 synced_at null (a key that is present), 21 null record
        for n in ["6", "7", "8", "9", "abc", "0", "-1", "1.5", "007", "15", "16", "17", "19", "20", "21"]:
            self.assertNotIn(("2026-10-28", n), seen, n)

    def test_each_ignore_rule_alone(self):
        entry = {"kind": "notion", "id": HEX_A}
        cases = {
            "open": {"status": "open", "by": "page"},
            "started": {"status": "started", "by": "page"},
            "chased": {"status": "chased", "by": "page"},
            "no by": {"status": "done"},
            "by claude": {"status": "done", "by": "claude"},
            "synced": page(synced_at="2026-10-28T10:00:00Z"),
            "synced null": page(synced_at=None),
            "status list": {"status": ["done"], "by": "page"},
            "status number": {"status": 1, "by": "page"},
            "record string": "done",
            "record list": ["done"],
            "record null": None,
        }
        for label, rec in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as d:
                s = Path(d)
                (s / "docs" / "brief-updates").mkdir(parents=True)
                (s / "state").mkdir()
                (s / "docs" / "brief-updates" / "2026-10-28.json").write_text(json.dumps({"items": {"1": rec}}))
                (s / "state" / "brief-map-2026-10-28.json").write_text(json.dumps({"numbers": {"1": entry}}))
                out = page_ticks.build(s / "docs", s / "state", NOW)
                self.assertEqual((out["pending"], out["skipped"], out["patches"]), ([], [], {}))

    def test_unusable_documents_are_ignored(self):
        out = fixture_out()
        dates = {t["date"] for t in out["pending"]} | {s["date"] for s in out["skipped"]}
        # 2026-10-26 does not parse, 2026-10-30 has items as a list, 2026-13-45 is not a date, notes.json is no date
        self.assertEqual(dates, {"2026-10-27", "2026-10-28", "2026-10-29"})


class Doc(Scratch):
    def test_non_object_documents_and_items(self):
        for raw in ["[]", '"x"', "null", "7", '{"items": null}', '{"items": "x"}', "{broken"]:
            with self.subTest(raw):
                (self.docs / "brief-updates" / "2026-10-28.json").write_text(raw)
                self.numbers("2026-10-28", {"1": {"kind": "notion", "id": HEX_A}})
                self.assertEqual(page_ticks.build(self.docs, self.state, NOW)["pending"], [])

    def test_non_utf8_file_is_ignored(self):
        (self.docs / "brief-updates" / "2026-10-28.json").write_bytes(b"\xff\xfe{")
        self.assertEqual(page_ticks.build(self.docs, self.state, NOW)["pending"], [])

    def test_missing_docs_dir_is_empty_output(self):
        out = page_ticks.build(self.docs / "nope", self.state, NOW)
        self.assertEqual(out, {"pending": [], "skipped": [], "patches": {},
                               "ack": {"task": [], "action": [], "test": []}})

    def test_numbers_sort_numerically_not_as_text(self):
        self.doc("2026-10-28", {"10": page(), "2": page(), "1": page()})
        self.numbers("2026-10-28", {n: {"kind": "notion", "id": c * 32} for n, c in [("1", "a"), ("2", "b"), ("10", "c")]})
        out = page_ticks.build(self.docs, self.state, NOW)
        self.assertEqual([t["n"] for t in out["pending"]], ["1", "2", "10"])


class KindsTest(Scratch):
    def test_notion(self):
        out = self.run_one(page(), {"kind": "notion", "id": HEX_A})
        self.assertEqual(out["pending"], [{"date": "2026-10-28", "n": "1", "kind": "notion", "id": HEX_A, "waiting": False}])
        self.assertEqual(out["ack"], {"task": [HEX_A], "action": [], "test": []})

    def test_notion_waiting(self):
        out = self.run_one(page(), {"kind": "notion", "id": HEX_A, "waiting": True})
        self.assertTrue(out["pending"][0]["waiting"])

    def test_waiting_must_be_the_boolean_true(self):
        for value in ["true", 1, None, "yes"]:
            out = self.run_one(page(), {"kind": "notion", "id": HEX_A, "waiting": value})
            self.assertFalse(out["pending"][0]["waiting"], value)

    def test_fathom(self):
        out = self.run_one(page(), {"kind": "fathom", "key": "f00d_BABE-12"})
        self.assertEqual(out["pending"][0]["key"], "f00d_BABE-12")
        self.assertNotIn("id", out["pending"][0])
        self.assertEqual(out["ack"], {"task": [], "action": ["f00d_BABE-12"], "test": []})

    def test_fathom_waiting(self):
        out = self.run_one(page(), {"kind": "fathom", "key": "abc123", "waiting": True})
        self.assertTrue(out["pending"][0]["waiting"])

    def test_test(self):
        out = self.run_one(page(), {"kind": "test", "key": "ekko-checkout#213"})
        self.assertEqual(out["pending"][0]["kind"], "test")
        self.assertEqual(out["pending"][0]["key"], "ekko-checkout#213")
        self.assertEqual(out["ack"], {"task": [], "action": [], "test": ["ekko-checkout#213"]})

    def test_only_test_ticks_carry_a_triage_url(self):
        out = fixture_out()
        for t in out["pending"]:
            self.assertEqual("triage_notion_url" in t, t["kind"] == "test")


class SkippedTest(Scratch):
    def skipped(self, entry):
        out = self.run_one(page(), entry)
        self.assertEqual(out["pending"], [])
        self.assertEqual(out["patches"], {})
        self.assertEqual(len(out["skipped"]), 1)
        self.assertEqual(out["skipped"][0]["date"], "2026-10-28")
        self.assertEqual(out["skipped"][0]["n"], "1")
        return out["skipped"][0]["reason"]

    def test_missing_map_file(self):
        self.doc("2026-10-28", {"1": page()})
        out = page_ticks.build(self.docs, self.state, NOW)
        self.assertEqual(out["skipped"], [{"date": "2026-10-28", "n": "1", "reason": "no brief map for that date"}])

    def test_unreadable_or_wrong_shape_map(self):
        self.doc("2026-10-28", {"1": page()})
        for raw in ["{broken", "[]", '{"numbers": []}', '{"numbers": null}', "{}"]:
            (self.state / "brief-map-2026-10-28.json").write_text(raw)
            out = page_ticks.build(self.docs, self.state, NOW)
            self.assertEqual([s["reason"] for s in out["skipped"]], ["no brief map for that date"], raw)

    def test_entry_missing(self):
        self.doc("2026-10-28", {"1": page()})
        self.numbers("2026-10-28", {"2": {"kind": "notion", "id": HEX_A}})
        out = page_ticks.build(self.docs, self.state, NOW)
        self.assertEqual(out["skipped"][0]["reason"], "not in the brief map")

    def test_entry_not_an_object(self):
        self.assertEqual(self.skipped("notion"), "not in the brief map")

    def test_unknown_or_missing_kind(self):
        self.assertEqual(self.skipped({"kind": "slack", "id": HEX_A}), "unknown kind in the brief map")
        self.assertEqual(self.skipped({"id": HEX_A}), "unknown kind in the brief map")

    def test_invalid_notion_ids(self):
        for bad in ["a" * 31, "a" * 33, "g" * 32, "", None, 5, ["a" * 32], "a" * 31 + "\n", "-".join(["aaaaaaaa"] * 4)]:
            with self.subTest(bad):
                self.assertEqual(self.skipped({"kind": "notion", "id": bad}), "invalid Notion id in the brief map")
        self.assertEqual(self.skipped({"kind": "notion"}), "invalid Notion id in the brief map")

    def test_invalid_fathom_keys(self):
        for bad in ["", "a" * 65, "bad key", "a/b", "a;b", "a\n", None, 12, ["x"]]:
            with self.subTest(bad):
                self.assertEqual(self.skipped({"kind": "fathom", "key": bad}), "invalid Fathom key in the brief map")

    def test_fathom_key_length_limits_are_valid(self):
        for ok in ["a", "a" * 64]:
            out = self.run_one(page(), {"kind": "fathom", "key": ok})
            self.assertEqual(len(out["pending"]), 1)

    def test_invalid_test_keys(self):
        for bad in ["ekko-api", "ekko-api#", "#12", "Ekko-API#12", "ekko api#12", "ekko-api#1a", "ekko-api#1\n", None, 3]:
            with self.subTest(bad):
                self.assertEqual(self.skipped({"kind": "test", "key": bad}), "invalid test key in the brief map")

    def test_junk_in_the_document_never_reaches_the_output(self):
        out = self.run_one(page(note="<script>alert(1)</script>", due="x" * 1000), {"kind": "notion", "id": "<img>"})
        self.assertNotIn("<", json.dumps(out))

    def test_skipped_ticks_do_not_block_valid_ones(self):
        self.doc("2026-10-28", {"1": page(), "2": page()})
        self.numbers("2026-10-28", {"1": {"kind": "notion", "id": "bad"}, "2": {"kind": "notion", "id": HEX_A}})
        out = page_ticks.build(self.docs, self.state, NOW)
        self.assertEqual([t["n"] for t in out["pending"]], ["2"])
        self.assertEqual([s["n"] for s in out["skipped"]], ["1"])
        self.assertEqual(out["patches"], {"2026-10-28": {"items": {"2": {"synced_at": NOW}}}})


class TriageUrlTest(Scratch):
    KEY = "ekko-checkout#213"

    def url_for(self, url):
        self.doc("2026-10-28", {"1": page()})
        self.numbers("2026-10-28", {"1": {"kind": "test", "key": self.KEY}})
        self.triage("2026-10-28", {self.KEY: {"notion_url": url}})
        return page_ticks.build(self.docs, self.state, NOW)["pending"][0]["triage_notion_url"]

    def test_kept_for_the_three_notion_hosts(self):
        for url in ["https://app.notion.com/p/" + HEX_A, "https://www.notion.so/" + HEX_A,
                    "https://notion.so/Some-Page-" + HEX_A, "https://www.notion.so/ws/page?pvs=4"]:
            self.assertEqual(self.url_for(url), url)

    def test_rejected(self):
        bad = ["http://app.notion.com/p/" + HEX_A, "https://evil.example.com/" + HEX_A,
               "https://notion.so.evil.example.com/x", "https://evil.example.com/notion.so",
               "https://notion.so@evil.example.com/x", "https://evil.example.com\\@notion.so/x",
               "https://app.notion.com:8443/p/x", "https://app.notion.com/p/x y", "https://app.notion.com/p/x\n",
               "javascript:alert(1)", "//notion.so/x", "notion.so/x", "", None, 5, ["https://notion.so/x"],
               "https://notion.so/" + "a" * 2000]
        for url in bad:
            with self.subTest(url):
                self.assertEqual(self.url_for(url), "")

    def test_no_triage_file_row_or_key(self):
        self.doc("2026-10-28", {"1": page()})
        self.numbers("2026-10-28", {"1": {"kind": "test", "key": self.KEY}})
        self.assertEqual(page_ticks.build(self.docs, self.state, NOW)["pending"][0]["triage_notion_url"], "")
        for raw in ["{broken", "[]", '{"prs": []}', '{"prs": {"other#1": {"notion_url": "https://notion.so/x"}}}',
                    '{"prs": {"%s": "x"}}' % self.KEY, '{"prs": {"%s": {}}}' % self.KEY]:
            (self.state / "triage-2026-10-28.json").write_text(raw)
            self.assertEqual(page_ticks.build(self.docs, self.state, NOW)["pending"][0]["triage_notion_url"], "", raw)

    def test_triage_is_read_per_date(self):
        for date in ["2026-10-27", "2026-10-28"]:
            self.doc(date, {"1": page()})
            self.numbers(date, {"1": {"kind": "test", "key": self.KEY}})
        self.triage("2026-10-28", {self.KEY: {"notion_url": "https://notion.so/x"}})
        out = page_ticks.build(self.docs, self.state, NOW)
        self.assertEqual([t["triage_notion_url"] for t in out["pending"]], ["", "https://notion.so/x"])

    def test_fixture_urls(self):
        by_n = {t["n"]: t for t in fixture_out()["pending"] if t["date"] == "2026-10-28"}
        self.assertEqual(by_n["3"]["triage_notion_url"], "https://app.notion.com/p/" + "7" * 32)
        self.assertEqual(by_n["4"]["triage_notion_url"], "")  # http link on another host
        self.assertEqual(by_n["5"]["triage_notion_url"], "")  # no triage row


class MultipleDatesTest(unittest.TestCase):
    def test_date_then_number_order_and_per_date_maps(self):
        out = fixture_out()
        # the same fathom key is in both maps, waiting only on the 28th
        fathom = [(t["date"], t["waiting"]) for t in out["pending"] if t["kind"] == "fathom"]
        self.assertEqual(fathom, [("2026-10-27", False), ("2026-10-28", True)])
        self.assertEqual([t["date"] for t in out["pending"]], sorted(t["date"] for t in out["pending"]))

    def test_date_without_a_map_is_skipped_not_dropped(self):
        out = fixture_out()
        self.assertIn({"date": "2026-10-29", "n": "1", "reason": "no brief map for that date"}, out["skipped"])


class PatchesAndAckTest(unittest.TestCase):
    def test_patches_cover_exactly_the_pending_ticks(self):
        out = fixture_out()
        from_patches = {(d, n) for d, p in out["patches"].items() for n in p["items"]}
        self.assertEqual(from_patches, {(t["date"], t["n"]) for t in out["pending"]})
        self.assertEqual(out["patches"]["2026-10-28"]["items"]["1"], {"synced_at": NOW})
        self.assertEqual(set(out["patches"]), {"2026-10-27", "2026-10-28"})
        for patch in out["patches"].values():
            self.assertEqual(list(patch), ["items"])

    def test_ack_is_deduplicated_and_in_order(self):
        ack = fixture_out()["ack"]
        # 2026-10-28 #1 and #18 share one Notion id; both dates share one Fathom key
        self.assertEqual(ack["task"], ["9" * 32, "8" * 32, "a" * 32])
        self.assertEqual(ack["action"], ["f00dbabe1234"])
        self.assertEqual(ack["test"], ["ekko-checkout#213", "ekko-api#1425", "ekko-web-mono#77"])

    def test_every_pending_value_is_acked(self):
        out = fixture_out()
        for t in out["pending"]:
            bucket = {"notion": "task", "fathom": "action", "test": "test"}[t["kind"]]
            self.assertIn(t.get("id") or t["key"], out["ack"][bucket])

    def test_output_shape(self):
        out = fixture_out()
        self.assertEqual(list(out), ["pending", "skipped", "patches", "ack"])
        self.assertEqual(list(out["ack"]), ["task", "action", "test"])
        for s in out["skipped"]:
            self.assertEqual(set(s), {"date", "n", "reason"})


class CliTest(Scratch):
    def test_now_is_used_for_synced_at(self):
        code, out, _ = run_cli(FIXTURES / "docs", FIXTURES / "state", "--now", "2030-01-02T03:04:05Z")
        self.assertEqual(code, 0)
        values = {i["synced_at"] for p in out["patches"].values() for i in p["items"].values()}
        self.assertEqual(values, {"2030-01-02T03:04:05Z"})

    def test_now_defaults_to_utc_now(self):
        code, out, _ = run_cli(FIXTURES / "docs", FIXTURES / "state")
        self.assertEqual(code, 0)
        value = out["patches"]["2026-10-28"]["items"]["1"]["synced_at"]
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertGreater(value, "2026-10-29")

    def test_empty_dirs_exit_zero_with_empty_output(self):
        code, out, _ = run_cli(self.docs, self.state)
        self.assertEqual(code, 0)
        self.assertEqual(out, {"pending": [], "skipped": [], "patches": {}, "ack": {"task": [], "action": [], "test": []}})

    def test_missing_dirs_still_exit_zero(self):
        code, out, _ = run_cli(self.docs / "nope", self.state / "nope")
        self.assertEqual(code, 0)
        self.assertEqual(out["pending"], [])

    def test_bad_arguments_exit_two(self):
        for args in [[], ["--docs-dir", "x"], ["--state-dir", "x"], ["--docs-dir", "x", "--state-dir", "y", "--bogus"]]:
            r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, args)

    def test_stdout_is_one_json_object_and_nothing_is_written(self):
        before = sorted(p.name for p in self.state.iterdir())
        r = subprocess.run([sys.executable, str(SCRIPT), "--docs-dir", str(FIXTURES / "docs"),
                            "--state-dir", str(FIXTURES / "state")], capture_output=True, text=True)
        self.assertIsInstance(json.loads(r.stdout), dict)
        self.assertEqual(r.stderr, "")
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
