#!/usr/bin/env python3
"""parse_initiatives.py — parse initiatives.md into JSON.

Usage:
    python3 parse_initiatives.py <path-to-initiatives.md>

Output (stdout): JSON array of initiatives, each:
    {
        "name": str,
        "yaml": {owner, status, linear_team?, github?, target_date?},
        "body": str   # free-text status, may be empty
    }

Exit codes:
    0 = success (even if zero initiatives — emits [])
    1 = file not found or unreadable
    2 = bad YAML in any initiative (the whole parse fails so the user fixes it)
"""

from __future__ import annotations
import datetime
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: pyyaml not installed. Run: python3 -m pip install --user pyyaml", file=sys.stderr)
    # Exit 0 with an empty result so the morning skill's parallel batch isn't cancelled.
    print("[]")
    sys.exit(0)


# H2 heading then anything until next H2 or EOF.
INITIATIVE_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# YAML block: ```yaml ... ```
YAML_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def parse(path: Path) -> list[dict]:
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        sys.exit(1)
    text = path.read_text(encoding="utf-8")

    # Find all H2 positions.
    matches = list(INITIATIVE_RE.finditer(text))
    if not matches:
        return []

    initiatives = []
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        # H1 sections (single #) are skipped — INITIATIVE_RE only matches "## " not "# ".
        # The H1 "# Initiatives" header at the top of the file is ignored by design.

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]

        # Extract YAML block.
        yaml_match = YAML_RE.search(section)
        yaml_data: dict = {}
        body = section
        if yaml_match:
            try:
                yaml_data = yaml.safe_load(yaml_match.group(1)) or {}
            except yaml.YAMLError as e:
                print(f"error: bad YAML in initiative '{name}': {e}", file=sys.stderr)
                sys.exit(2)
            # Body is what remains after stripping the YAML fence.
            body = section[:yaml_match.start()] + section[yaml_match.end():]

        body = body.strip()
        initiatives.append({"name": name, "yaml": yaml_data, "body": body})

    return initiatives


class _DateEncoder(json.JSONEncoder):
    """Serialise date/datetime objects produced by PyYAML as ISO strings."""
    def default(self, o: object) -> object:
        if isinstance(o, (datetime.date, datetime.datetime)):
            return o.isoformat()
        return super().default(o)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: parse_initiatives.py <path>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1]).expanduser()
    result = parse(path)
    print(json.dumps(result, indent=2, cls=_DateEncoder))


if __name__ == "__main__":
    main()
