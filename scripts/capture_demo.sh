#!/usr/bin/env bash
# Deterministic driver for the 60-second README demo (issue #15).
#
# Runs the three demo surfaces in sequence on a fresh clone with no API key:
#
#   1. scripts/render_regression_demo.py --no-screenshot
#      → writes docs/regression_demo.html, prints verdict + cosine.
#   2. (optional) open the HTML in the OS default browser so the
#      structured-slot diff + cosine panel show up in the recording.
#   3. prompt-snap diff against a tempdir snapshot, twice:
#        - --threshold 0.9   → pass on a near-paraphrase candidate.
#        - --threshold 0.99 --warn-band 0.0 → fail on the same candidate.
#      The committed examples/snapshots/refund_window_v1.yml uses an
#      8-dim illustrative embedding the default 128-dim hash embedder
#      can't compare to, so the script copies it to a tempdir and
#      re-baselines with `prompt-snap update --force` first. This is
#      the third bullet of the issue: "tighter tolerance making a
#      benign drift fail."
#
# The output is the recording — when JT records the GIF/video, this
# script's stdout is what gets captured. Hermetic: no API key, no network.
#
# Variables:
#   CAPTURE_PACE_SECONDS  pause between sections (default 2 for recording;
#                         test_capture_demo_smoke.py sets this to 0).
#   CAPTURE_OPEN_HTML     if "1" (default), open docs/regression_demo.html
#                         with the OS default opener after step 1. Smoke
#                         tests set this to "0".
#
# Exit: 0 on full success. The deliberately-failing diff at step 3 is
# wrapped in `|| true` so the script reaches the closing banner — the
# fail is the point of the surface, not a script error.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACE="${CAPTURE_PACE_SECONDS:-2}"
OPEN_HTML="${CAPTURE_OPEN_HTML:-1}"

banner() {
  printf '\n'
  printf '═══ %s\n' "$1"
  printf '\n'
}

pace() {
  if [ "$PACE" != "0" ]; then
    sleep "$PACE"
  fi
}

cd "$REPO_ROOT"

banner "prompt-regression-suite · 60-second demo"
printf 'three surfaces · hash embedder · no API key required\n'
pace

banner "1/3 · scripts/render_regression_demo.py"
printf 'rebuilds docs/regression_demo.html from the in-process synthetic snapshot.\n'
printf 'baseline keeps the integer "14 days"; upgraded drops it to "two weeks"\n'
printf '  + drops the eligibility caveat — diff layer catches both.\n\n'
python -u scripts/render_regression_demo.py --no-screenshot
pace

banner "2/3 · open docs/regression_demo.html"
printf 'browser tour: prompt panel · baseline · candidate · structured-slot table\n'
printf '  + cosine similarity (hash embedder) + verdict pill.\n'
HTML_PATH="$REPO_ROOT/docs/regression_demo.html"
if [ "$OPEN_HTML" = "1" ]; then
  if [ -f "$HTML_PATH" ]; then
    if command -v open >/dev/null 2>&1; then
      open "$HTML_PATH"
      printf '\nopened with `open`: %s\n' "$HTML_PATH"
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$HTML_PATH" >/dev/null 2>&1 &
      printf '\nopened with `xdg-open`: %s\n' "$HTML_PATH"
    else
      printf '\n(no OS opener found; HTML at: %s)\n' "$HTML_PATH"
    fi
  else
    printf '\n(step 1 did not produce %s — skipping open)\n' "$HTML_PATH"
  fi
else
  printf '\n(CAPTURE_OPEN_HTML=0 → browser launch skipped; HTML at: %s)\n' "$HTML_PATH"
fi
pace

banner "3/3 · prompt-snap diff · tighter tolerance flips pass → fail"
printf 're-baseline the example snapshot with the default 128-dim hash embedder\n'
printf '(committed copy carries an 8-dim illustrative embedding for docs).\n\n'

TMP_SNAP_DIR="$(mktemp -d -t prompt-regression-capture-XXXXXX)"
trap 'rm -rf "$TMP_SNAP_DIR"' EXIT
SNAP="$TMP_SNAP_DIR/refund_window_v1.yml"
cp "$REPO_ROOT/examples/snapshots/refund_window_v1.yml" "$SNAP"

# Canonical text we re-baseline against. Same string the committed
# snapshot ships — the only thing changing is the embedding, which we
# regenerate with the hash embedder so cosine comparisons work.
CANONICAL_TEXT='The Pro plan has a 14-day refund window from the original purchase date. Refunds during that window are full unless usage exceeds 25% of the included monthly quota, in which case the unused remainder is refunded.'

prompt-snap update --snapshot "$SNAP" --canonical "$CANONICAL_TEXT" --force
pace

# Near-paraphrase candidate: drops a single word + tightens phrasing.
# Hash embedder + 2-gram features keeps cosine high enough to pass at
# threshold 0.9 and low enough to fail at 0.99 with no warn band.
DRIFT_CANDIDATE='The Pro plan has a 14-day refund window from the original purchase date. Refunds during that window are full unless usage exceeds 25% of the included monthly quota, in which case the remainder is refunded.'

printf '\n─── diff #1 · --threshold 0.9 (default warn band)  →  expect: pass ───\n\n'
prompt-snap diff --snapshot "$SNAP" --candidate "$DRIFT_CANDIDATE" --threshold 0.9
pace

printf '\n─── diff #2 · --threshold 0.99 --warn-band 0.0  →  expect: fail ────\n\n'
# `|| true` so the deliberately-failing diff (exit 1 by design on the
# verdict=fail path) does not terminate the script before the closing
# banner runs.
prompt-snap diff --snapshot "$SNAP" --candidate "$DRIFT_CANDIDATE" --threshold 0.99 --warn-band 0.0 || true
pace

banner "demo complete"
printf 'all three surfaces ran end-to-end with zero API calls.\n'
printf 'recapture: scripts/capture_demo.sh (env: CAPTURE_PACE_SECONDS, CAPTURE_OPEN_HTML).\n'
