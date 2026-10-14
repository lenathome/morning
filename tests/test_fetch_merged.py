import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "fetch_merged.sh"

FAKE_GH = r'''#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    print(json.dumps([{
        "number": 154, "title": "t", "url": "u", "body": "",
        "mergedAt": "2026-10-13T12:50:05Z", "author": {"login": "x"},
        "mergeCommit": {"oid": "abc"}, "files": [{"path": "a.go"}],
    }]))
elif args[:2] == ["run", "list"]:
    runs = [{"workflowName": "Warden PR review", "status": "completed",
             "conclusion": "skipped", "databaseId": i} for i in range(1, 21)]
    runs.append({"workflowName": "Deploy Checkout App", "status": "completed",
                 "conclusion": "success", "databaseId": 999})
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 20
    print(json.dumps(runs[:limit]))
elif args[:2] == ["run", "view"] and args[2] == "999":
    print(json.dumps([{"name": "deploy-dev", "conclusion": "success"}]))
else:
    sys.exit(1)
'''


@unittest.skipUnless(shutil.which("jq"), "jq not installed")
class FetchMergedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        bin_dir = Path(self._tmp.name)
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    def tearDown(self):
        self._tmp.cleanup()

    def test_deploy_run_found_past_default_run_limit(self):
        r = subprocess.run(["bash", str(SCRIPT), "ekko-checkout", "3"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        prs = json.loads(r.stdout)
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]["deploys"], [{
            "workflow": "Deploy Checkout App", "status": "completed", "conclusion": "success",
            "jobs": [{"name": "deploy-dev", "conclusion": "success"}],
        }])


if __name__ == "__main__":
    unittest.main()
