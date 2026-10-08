#!/usr/bin/env bash
# prep_background.sh <input-image> <season>
# Shrink a photo for the morning brief: max 1600px on the long edge, low-quality JPEG
# (sips ignores a numeric formatOptions on this Mac, so "low" is used),
# saved as ~/morning/backgrounds/<season>.jpg. Needs macOS `sips`.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: prep_background.sh <input-image> <spring|summer|autumn|winter>" >&2
  exit 2
fi
input="$1"
season="$2"
case "$season" in
  spring|summer|autumn|winter) ;;
  *) echo "season must be spring, summer, autumn or winter (got: $season)" >&2; exit 2 ;;
esac
if [ ! -f "$input" ]; then
  echo "no such file: $input" >&2
  exit 2
fi

dir="$HOME/morning/backgrounds"
out="$dir/$season.jpg"
mkdir -p "$dir"
sips -Z 1600 -s format jpeg -s formatOptions low "$input" --out "$out" >/dev/null
bytes=$(wc -c < "$out" | tr -d ' ')
echo "wrote $out ($((bytes / 1024))KB)"
