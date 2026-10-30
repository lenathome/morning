#!/usr/bin/env python3
"""docs_drift.py - find public SDK options that changed in code while the developer docs still describe the old shape.

Usage:
    python3 docs_drift.py --config config.yaml --merged merged.json --state docs-drift.json --today 2026-10-29

Input:
    --config   YAML with a top-level `docs_drift` block:
                 lookback_days, docs_repo, docs_checkout, live_base,
                 watch: [{repo, file, guide, interfaces: {InterfaceName: dotted.prefix}}]
                 drafts (optional): [{title, file, branch, added, waiting_on?}] hand-listed docs pages not merged yet
               No block: prints [] and exits 0.
    --merged   output of fetch_merged.sh: [{repo, number, title, url, mergedAt, files, ...}].
               A repo without a slash means the ekko-enviroconomy org.
    --state    JSON {"items": {key: item}, "updated": date}. Missing or empty means {}. Rewritten each run.

Detection: for each merged PR (inside lookback_days) that touched a watched file, the file is read at the PR's
base and merge commits, and the direct members of each watched `export interface` are compared. A member
`Features.roundUp` becomes the dotted path `features.roundUp`. The guide is read from origin/main of the docs
checkout (code blocks by brace nesting, bullet lists by indent) and from the live page (<pre> blocks and nested
<ul>/<li>). Matching is by dotted path, never by bare word.

    removed path: still in source -> "stale"; only live -> "upload_pending"; neither -> no item.
    added path:   reported only when its parent path is documented in source; not in source -> "stale";
                  in source but not live -> "upload_pending"; in both -> no item.

If the live page cannot be fetched, live_checked is false and status comes from the source alone.

Drafts: each configured draft is listed as {status: "draft", title, branch, waiting_on, doc, first_seen, age_days}
until its file exists on origin/main of the docs checkout. If that check fails, the draft stays. Drafts are not
written to the state file: the config is their source of truth.

Output (stdout): a JSON array of {path, change, pr, doc, live_url, status, live_checked, first_seen, age_days},
sorted by age_days descending then path, followed by the drafts in config order. Items stay in the state file until
docs and code agree again.

Exit codes:
    0 = success (per-PR and per-fetch failures print one `warning:` line on stderr and are skipped)
    1 = invalid input (message on stderr)
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_ORG = "ekko-enviroconomy"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

NAMED_OPEN_RE = re.compile(r"^\s*(\w+)\??\s*:\s*\{")
LEAF_RE = re.compile(r"^\s*(?:readonly\s+)?(\w+)\??\s*:")
BULLET_RE = re.compile(r"^(\s*)[*+-]\s+`([\w.]+)`")
NAME_RE = re.compile(r"^[\w.]+$")
INTERFACE_RE = re.compile(r"export\s+interface\s+(\w+)[^{]*\{")


class InputError(Exception):
    pass


# ---- network, gh and git (patched in tests) ----------------------------------

def run_cmd(args) -> str:
    res = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {res.stderr.strip()[:200]}")
    return res.stdout


def gh_pr_shas(repo_full: str, number: int):
    """(base sha, merge commit sha) of a merged PR. Base is the merge commit's first parent when readable."""
    pr = json.loads(run_cmd(["gh", "api", f"repos/{repo_full}/pulls/{number}"]))
    base = pr["base"]["sha"]
    merge = pr["merge_commit_sha"]
    try:
        commit = json.loads(run_cmd(["gh", "api", f"repos/{repo_full}/commits/{merge}"]))
        base = commit["parents"][0]["sha"]
    except Exception:
        pass
    return base, merge


def gh_file_at(repo_full: str, path: str, sha: str) -> str:
    data = json.loads(run_cmd(["gh", "api", f"repos/{repo_full}/contents/{path}?ref={sha}"]))
    return base64.b64decode(data["content"]).decode("utf-8")


def git_fetch(checkout: str) -> None:
    run_cmd(["git", "-C", checkout, "fetch", "origin", "-q"])


def git_show(checkout: str, guide: str) -> str:
    return run_cmd(["git", "-C", checkout, "show", f"origin/main:{guide}"])


def git_on_main(checkout: str, file: str) -> bool:
    """True when the file exists on origin/main. A missing file is False; any other git failure raises."""
    try:
        run_cmd(["git", "-C", checkout, "cat-file", "-e", f"origin/main:{file}"])
        return True
    except RuntimeError as e:
        if "does not exist in" in str(e) or "exists on disk, but not in" in str(e):
            return False
        raise


def fetch_live(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---- parsing TypeScript interfaces -------------------------------------------

def mask(text: str) -> str:
    """Blank out comments and string contents, keeping length and newlines, so braces and names are safe to scan."""
    out, i, n = [], 0, len(text)
    blank = lambda s: re.sub(r"[^\n]", " ", s)
    while i < n:
        c, two = text[i], text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(blank(text[i:j]))
            i = j
        elif c in "\"'`":
            j = i + 1
            closed = False
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c:
                    closed = True
                    break
                if text[j] == "\n" and c != "`":
                    break
                j += 1
            j = min(j, n)
            out.append(c + re.sub(r"[^\n]", "_", text[i + 1:j]) + (c if closed else ""))
            i = j + 1 if closed else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_interfaces(text: str, wanted: dict) -> dict:
    """{dotted path} of direct members for each wanted interface name, using the configured prefix."""
    masked = mask(text)
    result = {}
    for m in INTERFACE_RE.finditer(masked):
        name = m.group(1)
        if name not in wanted:
            continue
        depth, i = 1, m.end()
        line_start_depth = 1
        line_start = i
        members = set()
        while i < len(masked) and depth > 0:
            ch = masked[i]
            if ch == "\n":
                line_start_depth = depth
                line_start = i + 1
                if line_start_depth == 1:
                    eol = masked.find("\n", line_start)
                    mm = LEAF_RE.match(masked[line_start:eol if eol >= 0 else len(masked)])
                    if mm:
                        members.add(mm.group(1))
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        # members declared on the opening line (`interface X { a: string }`) are rare and ignored
        prefix = wanted[name]
        result.setdefault(name, set()).update(f"{prefix}.{mem}" for mem in members)
    return result


# ---- parsing documentation ----------------------------------------------------

def parse_code(text: str, first_line: int = 1) -> dict:
    """Dotted paths documented in one code block -> first line number."""
    paths = {}
    stack = []  # one entry per open brace: a name, or None
    for offset, line in enumerate(mask(text).split("\n")):
        lineno = first_line + offset
        names = [s for s in stack if s]
        named = NAMED_OPEN_RE.match(line)
        if named:
            paths.setdefault(".".join(names + [named.group(1)]), lineno)
        else:
            leaf = LEAF_RE.match(line)
            if leaf:
                paths.setdefault(".".join(names + [leaf.group(1)]), lineno)
        first_open = True
        for ch in line:
            if ch == "{":
                stack.append(named.group(1) if (named and first_open) else None)
                first_open = False
            elif ch == "}" and stack:
                stack.pop()
    return paths


def parse_markdown(text: str) -> dict:
    """Dotted paths documented in a guide (code blocks and nested bullets) -> first line number."""
    paths = {}
    lines = text.split("\n")
    in_fence, block, block_start = False, [], 0
    bullets = []  # [(indent, name)]
    for idx, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            if in_fence:
                for p, n in parse_code("\n".join(block), block_start).items():
                    paths.setdefault(p, n)
                block = []
                in_fence = False
            else:
                in_fence, block_start = True, idx + 1
                bullets = []
            continue
        if in_fence:
            block.append(line)
            continue
        m = BULLET_RE.match(line)
        if m:
            indent = len(m.group(1).expandtabs(4))
            while bullets and bullets[-1][0] >= indent:
                bullets.pop()
            bullets.append((indent, m.group(2)))
            paths.setdefault(".".join(n for _, n in bullets), idx)
        elif line.strip() and not line.lstrip().startswith(("*", "-", "+")) and not line.startswith((" ", "\t")):
            bullets = []
    if in_fence:  # unterminated fence
        for p, n in parse_code("\n".join(block), block_start).items():
            paths.setdefault(p, n)
    return paths


class _LiveParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paths = set()
        self.in_pre = 0
        self.pre_buf = []
        self.li_stack = []  # [{"name": str|None, "child_list": bool}]
        self.code_buf = None
        self.code_is_name = False

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            if not self.in_pre:
                self.pre_buf = []
            self.in_pre += 1
        elif tag == "li":
            self.li_stack.append({"name": None, "child_list": False})
        elif tag == "ul" and self.li_stack:
            self.li_stack[-1]["child_list"] = True
        elif tag == "code" and not self.in_pre and self.code_buf is None:
            self.code_buf = []
            top = self.li_stack[-1] if self.li_stack else None
            self.code_is_name = bool(top and top["name"] is None and not top["child_list"])
        elif tag == "br" and self.in_pre:
            self.pre_buf.append("\n")

    def handle_endtag(self, tag):
        if tag == "pre" and self.in_pre:
            self.in_pre -= 1
            if not self.in_pre:
                self.paths.update(parse_code("".join(self.pre_buf)))
        elif tag == "li" and self.li_stack:
            self.li_stack.pop()
        elif tag == "code" and not self.in_pre and self.code_buf is not None:
            text = "".join(self.code_buf)
            self.code_buf = None
            if self.code_is_name and NAME_RE.match(text.strip()):
                self.li_stack[-1]["name"] = text.strip()
                names = [f["name"] for f in self.li_stack if f["name"]]
                self.paths.add(".".join(names))
            elif "\n" in text:
                self.paths.update(parse_code(text))
            self.code_is_name = False

    def handle_data(self, data):
        if self.in_pre:
            self.pre_buf.append(data)
        elif self.code_buf is not None:
            self.code_buf.append(data)


def parse_live(page: str) -> set:
    parser = _LiveParser()
    parser.feed(page)
    parser.close()
    return parser.paths


# ---- drift logic --------------------------------------------------------------

def classify(path: str, change: str, source: dict, live, live_checked: bool):
    """Status for one path, or None when docs and code agree (or nothing can be said)."""
    in_source = path in source
    in_live = live_checked and path in live
    if change == "removed":
        if in_source:
            return "stale"
        return "upload_pending" if in_live else None
    parent = path.rsplit(".", 1)[0] if "." in path else None
    if parent is None or parent not in source:
        return None
    if not in_source:
        return "stale"
    if live_checked and not in_live:
        return "upload_pending"
    return None


def diff_interfaces(before: dict, after: dict):
    """[(path, change)] across interfaces; removed first."""
    out = []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name, set()), after.get(name, set())
        out += [(p, "removed") for p in sorted(b - a)]
        out += [(p, "added") for p in sorted(a - b)]
    return out


def full_name(repo: str) -> str:
    return repo if "/" in repo else f"{DEFAULT_ORG}/{repo}"


def guide_url(cfg: dict, guide: str, line=None, ref: str = "main") -> str:
    url = f"https://github.com/{cfg['docs_repo']}/blob/{ref}/{guide}"
    return f"{url}#L{line}" if line else url


def live_url(cfg: dict, guide: str) -> str:
    return cfg["live_base"].rstrip("/") + "/" + Path(guide).stem


def make_item(cfg, entry, path, change, pr, status, line, live_checked, first_seen, today):
    owner_repo = full_name(pr["repo"])
    merged = (pr.get("mergedAt") or "")[:10] or pr.get("merged")
    return {
        "path": path,
        "change": change,
        "pr": {"repo": owner_repo.split("/", 1)[1], "number": pr["number"],
               "url": pr.get("url") or f"https://github.com/{owner_repo}/pull/{pr['number']}",
               "merged": merged},
        "doc": {"file": entry["guide"], "line": line, "url": guide_url(cfg, entry["guide"], line)},
        "live_url": live_url(cfg, entry["guide"]),
        "status": status,
        "live_checked": live_checked,
        "first_seen": first_seen.isoformat(),
        "age_days": (today - first_seen).days,
    }


def draft_items(cfg: dict, today: dt.date) -> list:
    """One item per configured draft whose file is not on origin/main yet, in config order."""
    out = []
    for d in cfg.get("drafts") or []:
        try:
            if git_on_main(os.path.expanduser(cfg["docs_checkout"]), d["file"]):
                continue
        except Exception as e:
            print(f"warning: cannot check draft {d['file']} on origin/main: {e}", file=sys.stderr)
        added = dt.date.fromisoformat(str(d["added"]))
        out.append({
            "status": "draft",
            "title": d["title"],
            "branch": d["branch"],
            "waiting_on": d.get("waiting_on"),
            "doc": {"file": d["file"], "line": None, "url": guide_url(cfg, d["file"], ref=d["branch"])},
            "first_seen": added.isoformat(),
            "age_days": max((today - added).days, 0),
        })
    return out


def load_state(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def load_docs(cfg: dict, guide: str):
    """(source paths dict or None, live paths set, live_checked)."""
    try:
        source = parse_markdown(git_show(os.path.expanduser(cfg["docs_checkout"]), guide))
    except Exception as e:
        print(f"warning: cannot read {guide} from the docs checkout: {e}", file=sys.stderr)
        return None, set(), False
    url = live_url(cfg, guide)
    try:
        return source, parse_live(fetch_live(url)), True
    except Exception as e:
        print(f"warning: cannot fetch {url}: {e}", file=sys.stderr)
        return source, set(), False


def run(cfg: dict, merged: list, stored: dict, today: dt.date):
    entries = cfg.get("watch") or []
    cutoff = today - dt.timedelta(days=int(cfg.get("lookback_days", 30)))
    try:
        git_fetch(os.path.expanduser(cfg["docs_checkout"]))
    except Exception as e:
        print(f"warning: git fetch failed in the docs checkout: {e}", file=sys.stderr)

    docs = {}  # guide -> (source, live, live_checked)
    def docs_for(guide):
        if guide not in docs:
            docs[guide] = load_docs(cfg, guide)
        return docs[guide]

    guide_entry = {e["guide"]: e for e in entries}
    items = {}

    # 1. re-check stored items
    for key, old in stored.items():
        try:
            guide = old["doc"]["file"]
            entry = guide_entry.get(guide)
            if entry is None:
                continue
            source, live, checked = docs_for(guide)
            if source is None:
                items[key] = old  # cannot judge: keep as it was
                continue
            status = classify(old["path"], old["change"], source, live, checked)
            if status is None and not checked and old.get("status") == "upload_pending":
                status = "upload_pending"
            if status is None:
                continue
            line = source.get(old["path"])
            new = dict(old)
            new.update({"status": status, "live_checked": checked,
                        "doc": {"file": guide, "line": line, "url": guide_url(cfg, guide, line)}})
            items[key] = new
        except Exception as e:
            print(f"warning: could not re-check {key}: {e}", file=sys.stderr)

    # 2. detect from newly merged PRs
    for pr in merged:
        try:
            repo_full = full_name(pr["repo"])
            merged_on = dt.date.fromisoformat((pr.get("mergedAt") or "")[:10])
            if merged_on < cutoff:
                continue
            for entry in entries:
                if full_name(entry["repo"]) != repo_full or entry["file"] not in (pr.get("files") or []):
                    continue
                base, head = gh_pr_shas(repo_full, pr["number"])
                wanted = entry["interfaces"]
                before = parse_interfaces(gh_file_at(repo_full, entry["file"], base), wanted)
                after = parse_interfaces(gh_file_at(repo_full, entry["file"], head), wanted)
                source, live, checked = docs_for(entry["guide"])
                if source is None:
                    continue
                for path, change in diff_interfaces(before, after):
                    status = classify(path, change, source, live, checked)
                    if status is None:
                        continue
                    key = f"{path}|{change}|{pr['repo']}#{pr['number']}"
                    first = items[key]["first_seen"] if key in items else None
                    if first is None and key in stored:
                        first = stored[key].get("first_seen")
                    # the docs fell behind when the PR merged, not when this run first noticed
                    first_seen = dt.date.fromisoformat(first) if first else min(merged_on, today)
                    items[key] = make_item(cfg, entry, path, change, pr, status, source.get(path),
                                           checked, first_seen, today)
        except Exception as e:
            print(f"warning: skipped PR {pr.get('repo')}#{pr.get('number')}: {e}", file=sys.stderr)

    # 3. ages
    for it in items.values():
        try:
            it["age_days"] = max((today - dt.date.fromisoformat(it["first_seen"])).days, 0)
        except (KeyError, ValueError):
            it["first_seen"], it["age_days"] = today.isoformat(), 0
    out = sorted(items.values(), key=lambda i: (-i["age_days"], i["path"]))
    return out, items


def load_config(path) -> dict:
    import yaml
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise InputError(f"cannot read config: {e}")
    block = data.get("docs_drift") if isinstance(data, dict) else None
    if not block:
        return {}
    if not isinstance(block, dict):
        raise InputError("docs_drift must be a mapping")
    for key in ("docs_repo", "docs_checkout", "live_base", "watch"):
        if not block.get(key):
            raise InputError(f"docs_drift.{key} is required")
    for i, w in enumerate(block["watch"]):
        if not isinstance(w, dict) or not all(w.get(k) for k in ("repo", "file", "guide", "interfaces")):
            raise InputError(f"docs_drift.watch[{i}] needs repo, file, guide and interfaces")
    drafts = block.get("drafts") or []
    if not isinstance(drafts, list):
        raise InputError("docs_drift.drafts must be a list")
    for i, d in enumerate(drafts):
        if not isinstance(d, dict) or not all(d.get(k) for k in ("title", "file", "branch", "added")):
            raise InputError(f"docs_drift.drafts[{i}] needs title, file, branch and added")
        try:
            dt.date.fromisoformat(str(d["added"]))
        except ValueError:
            raise InputError(f"docs_drift.drafts[{i}].added must be YYYY-MM-DD")
    return block


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Find SDK options changed in code but not in the docs.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--merged", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--today", required=True, help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    try:
        today = dt.date.fromisoformat(args.today)
    except ValueError:
        print(f"error: --today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
        return 1
    try:
        cfg = load_config(args.config)
        if not cfg:
            print("docs_drift: no docs_drift block in the config, skipped", file=sys.stderr)
            print("[]")
            return 0
        merged = json.loads(Path(args.merged).read_text(encoding="utf-8"))
        if not isinstance(merged, list):
            raise InputError("merged must be a JSON list")
    except (OSError, ValueError) as e:
        print(f"error: cannot read input: {e}", file=sys.stderr)
        return 1
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out, items = run(cfg, merged, load_state(args.state), today)
    Path(args.state).write_text(json.dumps({"items": items, "updated": today.isoformat()}, indent=2) + "\n",
                                encoding="utf-8")
    print(json.dumps(out + draft_items(cfg, today), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
