#!/usr/bin/env python3
"""Turn ticks made on the morning brief page into a list of "done" writes for Claude to carry out.

One file, standard library only, Python 3.9+, imports nothing from any repo.

    python3 /abs/path/page_ticks.py --docs-dir ~/morning/state/page-ticks --state-dir ~/morning/state [--now 2026-10-29T08:00:00Z]

What it does
- The model lists collection `brief-updates` of the brief page's db with ArtifactData (`list`, `out_dir` = --docs-dir). That
  writes one raw document per brief date to <docs-dir>/brief-updates/<YYYY-MM-DD>.json. This script reads those files and
  the number maps in --state-dir. It never calls Notion, Fathom or the page, and writes nothing.
- Prints exactly one JSON object to stdout and exits 0 whatever the input holds. Only bad arguments exit non-zero (2).
      {"pending": [{"date", "n", "kind", "id" | "key", "waiting", "triage_notion_url"?}],
       "skipped": [{"date", "n", "reason"}],
       "patches": {"<date>": {"items": {"<n>": {"synced_at": "<now>"}}}},
       "ack": {"task": [ids], "action": [keys], "test": [keys]}}
  `pending` is in date order, then number order. `patches` covers exactly the pending ticks: the model writes each patch
  with ArtifactData `update` only after the done-writes and ack scripts succeeded. `ack` is de-duplicated, in order.
  --now is the `synced_at` value; it defaults to the UTC time now, ISO 8601, seconds, `Z`.

Rules
1. The page database is written by whoever has the page open, so every field is untrusted data. Anything malformed is
   ignored, and no string from the documents is ever copied into the output except values that passed the checks below.
2. A file is read only when its name is `<YYYY-MM-DD>.json` with a real calendar date and it parses to a JSON object whose
   `items` is an object. Anything else is ignored.
3. A pending tick is an `items` record where the key is a positive integer string (no leading zero), the record is an
   object with `by` == "page", `status` == "done" and no `synced_at` key at all. An undo ({"status": "open", ...}), a
   started or chased record, a record written by Claude (no `by`) and an already synced tick are all ignored.
4. A pending tick is looked up in <state-dir>/brief-map-<date>.json (`numbers[<n>]`). It goes to `skipped`, with a short fixed
   reason, when the map is missing or unreadable, the entry is missing, or the entry is invalid: a notion `id` must be 32 hex
   characters, a fathom `key` 1 to 64 characters of [A-Za-z0-9_-], a test `key` must match ^[a-z0-9-]+#[0-9]+$.
   A skipped tick is not patched, so it shows as skipped again on the next run.
5. `waiting` is true only when the map entry has `waiting` set to true.
6. A test tick also gets `triage_notion_url` from <state-dir>/triage-<date>.json (`prs[key].notion_url`). It is kept only for
   an https link on app.notion.com, www.notion.so or notion.so with no user info, port, backslash or whitespace; anything
   else, or no row, gives "".
"""
import argparse, datetime, json, re, sys
from pathlib import Path
from urllib.parse import urlsplit

DATE_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')
N_RE = re.compile(r'^[1-9][0-9]{0,8}\Z')
NOTION_ID_RE = re.compile(r'^[0-9a-fA-F]{32}\Z')
FATHOM_KEY_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}\Z')
TEST_KEY_RE = re.compile(r'^[a-z0-9-]+#[0-9]+\Z')
NOTION_HOSTS = {'app.notion.com', 'www.notion.so', 'notion.so'}
BAD_URL_CHAR_RE = re.compile(r'[\\\s\x00-\x1f\x7f-\x9f]')
MAX_URL_LEN = 2000


def read_json(path):
    """The parsed JSON in path, or None when it is missing, unreadable or not JSON."""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, RecursionError):
        return None


def valid_date(name):
    """True for a real calendar date written YYYY-MM-DD."""
    if not isinstance(name, str) or not DATE_RE.match(name):
        return False
    try:
        datetime.date.fromisoformat(name)
    except ValueError:
        return False
    return True


def is_pending(n, rec):
    """True for a tick the page wrote and Claude has not synced."""
    return (isinstance(n, str) and N_RE.match(n) is not None and isinstance(rec, dict)
            and rec.get('by') == 'page' and rec.get('status') == 'done' and 'synced_at' not in rec)


def pending_ticks(docs_dir):
    """[(date, n)] for every pending tick under <docs_dir>/brief-updates, in date then number order."""
    out = []
    folder = Path(docs_dir) / 'brief-updates'
    try:
        names = sorted(p.name for p in folder.iterdir() if p.name.endswith('.json'))
    except OSError:
        return out
    for name in names:
        date = name[:-len('.json')]
        if not valid_date(date):
            continue
        doc = read_json(folder / name)
        items = doc.get('items') if isinstance(doc, dict) else None
        if not isinstance(items, dict):
            continue
        out.extend((date, n) for n in sorted((k for k, v in items.items() if is_pending(k, v)), key=int))
    return out


def resolve(entry):
    """(fields, None) for a valid map entry, or (None, reason). Fields: kind, id or key, waiting."""
    if not isinstance(entry, dict):
        return None, 'not in the brief map'
    kind = entry.get('kind')
    waiting = entry.get('waiting') is True
    if kind == 'notion':
        value = entry.get('id')
        if isinstance(value, str) and NOTION_ID_RE.match(value):
            return {'kind': kind, 'id': value, 'waiting': waiting}, None
        return None, 'invalid Notion id in the brief map'
    if kind == 'fathom':
        value = entry.get('key')
        if isinstance(value, str) and FATHOM_KEY_RE.match(value):
            return {'kind': kind, 'key': value, 'waiting': waiting}, None
        return None, 'invalid Fathom key in the brief map'
    if kind == 'test':
        value = entry.get('key')
        if isinstance(value, str) and TEST_KEY_RE.match(value):
            return {'kind': kind, 'key': value, 'waiting': waiting}, None
        return None, 'invalid test key in the brief map'
    return None, 'unknown kind in the brief map'


def triage_url(triage, key):
    """The Notion triage row URL for a test key, or '' when there is no safe one."""
    prs = triage.get('prs') if isinstance(triage, dict) else None
    row = prs.get(key) if isinstance(prs, dict) else None
    url = row.get('notion_url') if isinstance(row, dict) else None
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LEN or BAD_URL_CHAR_RE.search(url):
        return ''
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return ''
    if parts.scheme != 'https' or parts.hostname not in NOTION_HOSTS or '@' in parts.netloc or port is not None:
        return ''
    return url


def build(docs_dir, state_dir, now):
    """The whole output object."""
    state = Path(state_dir)
    maps, triages = {}, {}
    pending, skipped = [], []
    for date, n in pending_ticks(docs_dir):
        if date not in maps:
            data = read_json(state / f'brief-map-{date}.json')
            numbers = data.get('numbers') if isinstance(data, dict) else None
            maps[date] = numbers if isinstance(numbers, dict) else None
        if maps[date] is None:
            skipped.append({'date': date, 'n': n, 'reason': 'no brief map for that date'})
            continue
        fields, reason = resolve(maps[date].get(n))
        if fields is None:
            skipped.append({'date': date, 'n': n, 'reason': reason})
            continue
        tick = {'date': date, 'n': n, **fields}
        if fields['kind'] == 'test':
            if date not in triages:
                triages[date] = read_json(state / f'triage-{date}.json')
            tick['triage_notion_url'] = triage_url(triages[date], fields['key'])
        pending.append(tick)
    return {'pending': pending, 'skipped': skipped, 'patches': patches(pending, now), 'ack': acks(pending)}


def patches(pending, now):
    """One db patch per date, covering exactly the pending ticks."""
    out = {}
    for t in pending:
        out.setdefault(t['date'], {'items': {}})['items'][t['n']] = {'synced_at': now}
    return out


def acks(pending):
    """The ids and keys for the ack scripts, de-duplicated, in tick order."""
    out = {'task': [], 'action': [], 'test': []}
    for t in pending:
        bucket, value = {'notion': ('task', t.get('id')), 'fathom': ('action', t.get('key')),
                         'test': ('test', t.get('key'))}[t['kind']]
        if value not in out[bucket]:
            out[bucket].append(value)
    return out


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def main(argv=None):
    ap = argparse.ArgumentParser(description='List the page ticks that still need syncing.')
    ap.add_argument('--docs-dir', required=True)
    ap.add_argument('--state-dir', required=True)
    ap.add_argument('--now', default=None)
    args = ap.parse_args(argv)
    now = args.now or utc_now()
    print(json.dumps(build(args.docs_dir, args.state_dir, now), indent=2))


if __name__ == '__main__':
    main()
