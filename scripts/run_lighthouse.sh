#!/usr/bin/env bash
# Lighthouse wrapper for the web-app-release-skill.
#
# Usage:
#   run_lighthouse.sh <url> [more-urls...] [--output-dir DIR]
#
# Runs mobile-emulated Lighthouse per URL, writes JSON+HTML reports, and prints
# category scores with the reference thresholds used by the skill
# (Performance >= 90, SEO >= 95, Best Practices >= 95, Accessibility -> 100).
# Exits 0 even when scores are below thresholds — scoring/judgment belongs to
# the agent; this wrapper only produces evidence.
set -uo pipefail

OUT_DIR="release-audit/lighthouse"
URLS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --output-dir) OUT_DIR="$2"; shift 2 ;;
    *) URLS+=("$1"); shift ;;
  esac
done

if [ ${#URLS[@]} -eq 0 ]; then
  echo "usage: run_lighthouse.sh <url> [more-urls...] [--output-dir DIR]" >&2
  exit 2
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "SKIP: npx not found; install Node.js to run Lighthouse. Remaining checks stay manual."
  exit 0
fi

CHROME="${CHROME_PATH:-}"
if [ -z "$CHROME" ]; then
  for c in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$c" >/dev/null 2>&1; then CHROME="$(command -v "$c")"; break; fi
  done
fi
if [ -z "$CHROME" ]; then
  echo "SKIP: no Chrome/Chromium found; Lighthouse needs a browser. Remaining checks stay manual."
  exit 0
fi

mkdir -p "$OUT_DIR"
for url in "${URLS[@]}"; do
  slug=$(printf '%s' "$url" | sed -e 's|^[a-z]*://||' -e 's|[^A-Za-z0-9._-]|_|g' | cut -c1-80)
  slug=${slug%.*}   # lighthouse strips output-path extensions; keep names in sync
  base="$OUT_DIR/$slug"
  echo ">> lighthouse: $url"
  if ! npx --yes lighthouse "$url" \
        --quiet --chrome-flags="--headless=new" \
        --output json --output html \
        --output-path "$base" ; then
    echo "WARN: lighthouse run failed for $url (see $base); treat performance as manual."
    continue
  fi
  python3 - "$base.report.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except (OSError, ValueError) as e:
    print(f"   WARN: could not parse {sys.argv[1]}: {e}")
    sys.exit(0)
for k in ("performance", "seo", "best-practices", "accessibility"):
    c = d.get("categories", {}).get(k)
    if c and c.get("score") is not None:
        print(f"   {k}: {round(c['score']*100)}")
PY
done

echo ">> reference thresholds: performance>=90 seo>=95 best-practices>=95 accessibility->100"
echo ">> reports in $OUT_DIR (judgment on failures: see references/domains.md)"
exit 0
