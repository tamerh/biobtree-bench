#!/usr/bin/env bash
# Poll the live Sugi Variant deployment until the acceptance checks pass.
# Checks every 30 min, up to 8 hours. Logs to /tmp/opencode/variant_watch.log.
set -u
cd "$(dirname "$0")"
LOG=/tmp/opencode/variant_watch.log
LATEST=/tmp/opencode/variant_check_latest.txt
echo "=== watch started $(date -Is) ===" >> "$LOG"
for i in $(seq 1 16); do
    if python3 check_variant_release.py > "$LATEST" 2>&1; then
        echo "READY $(date -Is)" >> "$LOG"
        cat "$LATEST" >> "$LOG"
        exit 0
    fi
    echo "not ready $(date -Is)" >> "$LOG"
    grep -E '^(PASS|FAIL|WARN|release)' "$LATEST" >> "$LOG"
    sleep 1800
done
echo "TIMEOUT $(date -Is)" >> "$LOG"
exit 1
