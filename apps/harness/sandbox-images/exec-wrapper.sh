#!/bin/sh
# Bounded I/O wrapper: hard wall-clock timeout + output cap.
set -u
TIMEOUT_MS="${1:-15000}"
MAX_BYTES="${2:-65536}"
shift 2 2>/dev/null || true
if [ "$#" -eq 0 ]; then echo "usage: exec-wrapper <timeout_ms> <max_bytes> <cmd...>" >&2; exit 2; fi
OUT="$(mktemp)"
start=$(date +%s%3N)
( "$@" >"$OUT" 2>&1 & pid=$!; ( sleep "$(awk "BEGIN{print $TIMEOUT_MS/1000}")" && kill "$pid" 2>/dev/null ) & killer=$!; wait "$pid"; rc=$?; kill "$killer" 2>/dev/null; echo "$rc" >&3 ) 3>"$OUT.rc"
rc=$(cat "$OUT.rc" 2>/dev/null || echo 137)
end=$(date +%s%3N)
bytes=$(wc -c <"$OUT")
if [ "$bytes" -gt "$MAX_BYTES" ]; then
  head -c "$MAX_BYTES" "$OUT" >"$OUT.cap"
  mv "$OUT.cap" "$OUT"
fi
cat "$OUT"
printf '\n[io-wrapper] exit=%s bytes=%s elapsed_ms=%s\n' "$rc" "$bytes" "$((end-start))" >&2
rm -f "$OUT" "$OUT.rc"
exit "$rc"