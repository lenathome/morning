"""Turn the raw Notion "Testing triage" query result into the triage file for one morning brief.

One file, standard library only, Python 3.9+, imports nothing from any repo. It replaces `pr_triage_reader.py`.

    python3 /abs/path/triage_from_notion.py --rows /abs/path/notion-rows.json --brief-date 2026-10-26 \\
        --out /abs/path/morning/state/triage-2026-10-26.json

What it does
- Each morning the model queries the Notion database "Testing triage" (one row per PR) with the Notion connector and
  saves the raw result, `{"results": [...]}`, to --rows. This script reads that file only. It never calls Notion
  or GitHub, and never follows or fetches anything it reads.
- Writes one JSON file to --out (atomically) and prints exactly one line:
      triage: ok (3 PRs)
      triage: ok (3 PRs); skipped bad key: Some title
      triage: unavailable (rows file is not valid JSON)
  It always exits 0, so the brief carries on. On failure it still writes {"status": "unavailable", "reason": ...}
  so `render_brief.py` shows the right banner. Only bad arguments exit non-zero.
- Output on success: {"status": "ok", "source": "notion", "valid_for": <brief date>, "read_at", "run_id": null,
  "trial": the trial banner object, "group_notes": {}, "withheld": [], "prs": {"<repo>#<number>": card}}.
  `render_brief.join_triage` joins `prs` onto the Testing items by that key.

Rules
1. Only rows with "On the Testing list" set to __YES__ are kept.
2. A key must match ^[a-z0-9-]+#[0-9]+$. A row with any other key is skipped and named in the status line.
3. `notion_url` is kept only for https links on app.notion.com, www.notion.so or notion.so; a bare
   app.notion.com/<id> link gets /p/ added, because without it the page is a 404. `pr_url` is kept only
   for https://github.com/ekko-enviroconomy/... links. Anything else becomes "".
4. Every string is data from someone else's tool: control characters are removed, it is cut to 500 characters and
   it is never evaluated. In the file, `<`, `>` and `&` are written as \\u escapes so it can sit in a <script> block.
5. Input that is not valid JSON, or has no `results` list, makes the run unavailable.
"""
import argparse, datetime, json, os, pathlib, re, sys, tempfile
from urllib.parse import urlsplit

KEY_RE = re.compile(r'^[a-z0-9-]+#[0-9]+\Z')
DATE_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')
CONTROL_RE = re.compile(r'[\x00-\x1f\x7f-\x9f  ]')
MAX_LEN = 500
NOTION_HOSTS = {'app.notion.com', 'www.notion.so', 'notion.so'}
BARE_NOTION_PAGE_RE = re.compile(r'^(https://app\.notion\.com)/([0-9a-fA-F]{32})(\?[^#]*)?\Z')
PR_URL_PREFIX = 'https://github.com/ekko-enviroconomy/'

TRIAL = {
    'active': True,
    'banner': 'TRIAL: keep testing as normal.',
    'detail': 'The trial rules are unchanged: test as normal, including the checks the tool calls proven.',
}


def clean(x):
    """A string from the data: controls out, trimmed, capped. Anything that is not a string becomes ''."""
    if not isinstance(x, str):
        return ''
    return CONTROL_RE.sub('', x.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')).strip()[:MAX_LEN]


def number(x):
    """An int, or None. Bools and non-finite values are not numbers."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if isinstance(x, float):
        if x != x or x in (float('inf'), float('-inf')):
            return None
        return int(round(x))
    return x


def checked(x):
    return x == '__YES__'


def safe_url(url, ok):
    url = clean(url)
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        return ''
    return url if parts.scheme == 'https' and ok(host, url) else ''


def notion_url(x):
    url = safe_url(x, lambda host, url: host in NOTION_HOSTS)
    return BARE_NOTION_PAGE_RE.sub(r'\1/p/\2\3', url)


def pr_url(x):
    return safe_url(x, lambda host, url: host == 'github.com' and url.startswith(PR_URL_PREFIX))


def changed_on(x):
    s = clean(x)
    if DATE_RE.match(s):
        try:
            datetime.date.fromisoformat(s)
            return s
        except ValueError:
            pass
    return ''


def card(row, key):
    title = clean(row.get('PR'))
    if title.startswith(key + ' '):
        title = title[len(key) + 1:].strip()
    return {
        'title': title,
        'label': clean(row.get('Label')),
        'risk': clean(row.get('Risk')),
        'deploy': {'dev': clean(row.get('Dev')), 'staging': clean(row.get('Staging')), 'prod': clean(row.get('Prod'))},
        'on_prod': checked(row.get('On prod')),
        'totals': {'checks': number(row.get('Checks')), 'checks_that_matter': number(row.get('Checks that matter')),
                   'minutes': number(row.get('Minutes'))},
        'last_change': clean(row.get('Last change')),
        'changed_on': changed_on(row.get('date:Changed on:start')),
        'status': clean(row.get('Status')),
        'notes': clean(row.get('Notes')),
        'notion_url': notion_url(row.get('url')),
        'pr_url': pr_url(row.get('Link')),
    }


def unavailable(reason):
    return {'status': 'unavailable', 'reason': reason}, f'triage: unavailable ({reason})'


def convert(text, brief_date, now=None):
    """(output object, status line) for the raw rows file text."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return unavailable('rows file is not valid JSON')
    rows = data.get('results') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return unavailable('rows file has no results list')
    prs, skipped = {}, []
    for row in rows:
        if not isinstance(row, dict) or not checked(row.get('On the Testing list')):
            continue
        key = row.get('Key')
        if not isinstance(key, str) or not KEY_RE.match(key):
            skipped.append(clean(row.get('PR')) or clean(key) or 'unnamed row')
            continue
        prs[key] = card(row, key)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = {'status': 'ok', 'source': 'notion', 'valid_for': brief_date,
           'read_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'run_id': None, 'trial': dict(TRIAL),
           'group_notes': {}, 'withheld': [], 'prs': prs}
    line = f"triage: ok ({len(prs)} PR{'' if len(prs) == 1 else 's'})"
    if skipped:
        line += f"; skipped bad key: {', '.join(skipped)}"
    return out, line


def dumps_safe(obj):
    """JSON with <, > and & escaped: the same strings, but safe to embed in an HTML <script> block."""
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    return text.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026') + '\n'


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rows', required=True, help='the raw Notion query result, JSON')
    ap.add_argument('--brief-date', required=True, help="today's brief date, YYYY-MM-DD")
    ap.add_argument('--out', required=True, help='where to write the JSON, e.g. ~/morning/state/triage-<date>.json')
    a = ap.parse_args(argv)
    try:
        if not DATE_RE.match(a.brief_date):
            raise ValueError
        datetime.date.fromisoformat(a.brief_date)
    except ValueError:
        ap.error('--brief-date must be YYYY-MM-DD')
    try:
        text = pathlib.Path(a.rows).expanduser().read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        out, line = unavailable('cannot read rows file')
    else:
        out, line = convert(text, a.brief_date)
    try:
        write_atomic(pathlib.Path(a.out).expanduser(), dumps_safe(out))
    except OSError:
        line = 'triage: unavailable (cannot write output)'
    print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
