import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_sessions.py"
sys.path.insert(0, str(SCRIPT.parent))
import extract_sessions  # noqa: E402

SINCE = "2026-09-29T10:00:00Z"
SINCE_DT = extract_sessions.parse_ts(SINCE)


def user(ts, content, **extra):
    e = {"type": "user", "isSidechain": False, "timestamp": ts, "sessionId": "s1",
         "cwd": "/Users/x", "gitBranch": "main", "turnOrigin": "human",
         "origin": {"kind": "human"}, "message": {"role": "user", "content": content}}
    e.update(extra)
    return e


def assistant(ts, text, **extra):
    e = {"type": "assistant", "timestamp": ts, "sessionId": "s1",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "hmm"},
             {"type": "text", "text": text},
             {"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]}}
    e.update(extra)
    return e


def write_session(root: Path, project: str, name: str, entries, raw_lines=()):
    p = root / project / name
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in entries] + list(raw_lines)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_extract(self, exclude=None):
        return extract_sessions.extract(self.root, SINCE_DT, exclude)

    def test_time_filter_is_strict_and_uses_kept_range(self):
        write_session(self.root, "p", "s1.jsonl", [
            user("2026-09-29T09:00:00Z", "old question"),
            user("2026-09-29T10:00:00Z", "exactly at since"),
            user("2026-09-29T11:00:00Z", "new question"),
            assistant("2026-09-29T11:01:00Z", "new answer"),
        ])
        [s] = self.run_extract()
        self.assertEqual([m["text"] for m in s["messages"]], ["new question", "new answer"])
        self.assertEqual(s["started_at"], "2026-09-29T11:00:00Z")
        self.assertEqual(s["ended_at"], "2026-09-29T11:01:00Z")
        self.assertEqual(s["human_turns"], 1)
        self.assertEqual(s["session_id"], "s1")
        self.assertEqual(s["cwd"], "/Users/x")
        self.assertEqual(s["git_branch"], "main")

    def test_session_fully_before_since_dropped(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-28T09:00:00Z", "old")])
        self.assertEqual(self.run_extract(), [])

    def test_old_mtime_file_skipped(self):
        p = write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "hi")])
        os.utime(p, (0, 0))
        self.assertEqual(self.run_extract(), [])

    def test_offset_formats_accepted(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00+00:00", "hi")])
        self.assertEqual(len(extract_sessions.extract(
            self.root, extract_sessions.parse_ts("2026-09-29T10:00:00+00:00"), None)), 1)

    def test_sidechain_excluded(self):
        write_session(self.root, "p", "s1.jsonl", [
            user("2026-09-29T11:00:00Z", "main"),
            user("2026-09-29T11:01:00Z", "side", isSidechain=True),
            assistant("2026-09-29T11:02:00Z", "side answer", isSidechain=True),
        ])
        [s] = self.run_extract()
        self.assertEqual([m["text"] for m in s["messages"]], ["main"])

    def test_sidechain_only_session_dropped(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "x", isSidechain=True)])
        self.assertEqual(self.run_extract(), [])

    def test_subdirectory_files_ignored(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "top")])
        write_session(self.root, "p/s1/subagents", "agent.jsonl",
                      [user("2026-09-29T11:00:00Z", "sub", sessionId="sub")])
        write_session(self.root, ".", "loose.jsonl", [user("2026-09-29T11:00:00Z", "loose", sessionId="l")])
        result = self.run_extract()
        self.assertEqual([s["session_id"] for s in result], ["s1"])

    def test_tool_result_not_human(self):
        write_session(self.root, "p", "s1.jsonl", [
            user("2026-09-29T11:00:00Z", [{"type": "tool_result", "tool_use_id": "t", "content": "out"}]),
            assistant("2026-09-29T11:01:00Z", "answer"),
        ])
        self.assertEqual(self.run_extract(), [])

    def test_list_content_text_blocks_are_human(self):
        write_session(self.root, "p", "s1.jsonl", [
            user("2026-09-29T11:00:00Z", [{"type": "text", "text": "hello"}]),
            user("2026-09-29T11:01:00Z", [{"type": "tool_result", "content": "x"}]),
        ])
        [s] = self.run_extract()
        self.assertEqual(s["human_turns"], 1)
        self.assertEqual(len(s["messages"]), 1)

    def test_non_human_origin_not_counted(self):
        e = user("2026-09-29T11:00:00Z", "auto", turnOrigin="scheduled", origin={"kind": "scheduled"})
        write_session(self.root, "p", "s1.jsonl", [e])
        self.assertEqual(self.run_extract(), [])

    def test_missing_origin_fields_count_as_human(self):
        e = user("2026-09-29T11:00:00Z", "plain")
        del e["turnOrigin"], e["origin"]
        write_session(self.root, "p", "s1.jsonl", [e])
        self.assertEqual(self.run_extract()[0]["human_turns"], 1)

    def test_scheduled_task_detected(self):
        text = '<scheduled-task name="morning-sweep" file="x">do it</scheduled-task>'
        write_session(self.root, "p", "s1.jsonl", [
            user("2026-09-29T11:00:00Z", text),
            user("2026-09-29T11:01:00Z", "follow up"),
        ])
        [s] = self.run_extract()
        self.assertEqual(s["scheduled_task"], "morning-sweep")

    def test_scheduled_task_null_by_default(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "hi")])
        self.assertIsNone(self.run_extract()[0]["scheduled_task"])

    def test_title_last_wins_and_alt_key(self):
        write_session(self.root, "p", "s1.jsonl", [
            {"type": "custom-title", "customTitle": "First"},
            user("2026-09-29T11:00:00Z", "hi"),
            {"type": "custom-title", "customTitle": "Second"},
        ])
        write_session(self.root, "p", "s2.jsonl", [
            {"type": "custom-title", "title": "Alt"},
            user("2026-09-29T12:00:00Z", "hi", sessionId="s2"),
        ])
        write_session(self.root, "p", "s3.jsonl", [user("2026-09-29T13:00:00Z", "hi", sessionId="s3")])
        titles = {s["session_id"]: s["title"] for s in self.run_extract()}
        self.assertEqual(titles, {"s1": "Second", "s2": "Alt", "s3": None})

    def test_message_truncated(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "a" * 2500)])
        [s] = self.run_extract()
        text = s["messages"][0]["text"]
        self.assertEqual(text, "a" * 2000 + "…[truncated]")

    def test_session_truncated_keeps_head_and_tail(self):
        entries = []
        for i in range(60):
            ts = f"2026-09-29T11:{i:02d}:00Z"
            entries.append(user(ts, f"m{i:02d}" + "x" * 1997))
        write_session(self.root, "p", "s1.jsonl", entries)
        [s] = self.run_extract()
        msgs = s["messages"]
        self.assertEqual([m["text"][:3] for m in msgs[:5]], ["m00", "m01", "m02", "m03", "m04"])
        notes = [m for m in msgs if m["role"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIsNone(notes[0]["at"])
        self.assertEqual(msgs[5], notes[0])
        omitted = int(notes[0]["text"].strip("[]").split()[0])
        self.assertEqual(omitted + len(msgs) - 1, 60)
        self.assertTrue(msgs[-1]["text"].startswith("m59"))
        total = sum(len(m["text"]) for m in msgs if m["role"] != "note")
        self.assertLessEqual(total, 40000)

    def test_exclude_session(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "a")])
        write_session(self.root, "p", "s2.jsonl", [user("2026-09-29T12:00:00Z", "b", sessionId="s2")])
        self.assertEqual([s["session_id"] for s in self.run_extract(exclude="s1")], ["s2"])

    def test_session_id_falls_back_to_filename(self):
        e = user("2026-09-29T11:00:00Z", "a")
        del e["sessionId"]
        write_session(self.root, "p", "abc123.jsonl", [e])
        self.assertEqual(self.run_extract()[0]["session_id"], "abc123")

    def test_malformed_lines_skipped(self):
        write_session(self.root, "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "ok")],
                      raw_lines=["{not json", "[1,2]", '{"type":"user","timestamp":"bad"}'])
        self.assertEqual(len(self.run_extract()), 1)

    def test_sorted_by_started_at(self):
        write_session(self.root, "p", "b.jsonl", [user("2026-09-29T13:00:00Z", "later", sessionId="b")])
        write_session(self.root, "q", "a.jsonl", [user("2026-09-29T11:00:00Z", "earlier", sessionId="a")])
        self.assertEqual([s["session_id"] for s in self.run_extract()], ["a", "b"])


class CliTests(unittest.TestCase):
    def test_bad_since_exits_2(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--since", "yesterday-ish"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--since", r.stderr)

    def test_cli_outputs_json(self):
        with tempfile.TemporaryDirectory() as d:
            write_session(Path(d), "p", "s1.jsonl", [user("2026-09-29T11:00:00Z", "hi")])
            r = subprocess.run([sys.executable, str(SCRIPT), "--since", "2026-09-29T10:00:00+00:00",
                                "--projects-dir", d], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)[0]["session_id"], "s1")


if __name__ == "__main__":
    unittest.main()
