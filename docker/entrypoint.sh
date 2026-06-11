#!/bin/sh
# Run `python -m app.main <args>` on a loop, sleeping between scans.
#
# - Args passed to the container (the Docker CMD) are forwarded as-is, e.g.
#   `--live`, `--offline-test`, `--evaluate-history`, `--no-history`, ...
# - SCREENER_RUN_INTERVAL_SECONDS controls the sleep between runs (default 300).
# - A failed run is logged but never kills the loop — same "never break the
#   screener" philosophy as the history layer inside the app.
set -u

INTERVAL="${SCREENER_RUN_INTERVAL_SECONDS:-300}"

while true; do
    echo "=== $(date -u +'%Y-%m-%dT%H:%M:%SZ') crypto_screener run (args: $*) ==="
    python -m app.main "$@"
    status=$?
    if [ "$status" -ne 0 ]; then
        echo "warning: screener run exited with status $status" >&2
    fi
    echo "--- sleeping ${INTERVAL}s ---"
    sleep "$INTERVAL"
done
