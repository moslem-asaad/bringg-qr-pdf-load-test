#!/usr/bin/env bash
# BRNGG-55375 — Case 9: concurrent duplicate run:started
#
# Fires two PATCH /automation/run/:id requests back-to-back (truly in parallel, via
# backgrounded curl + wait) so two run:started events land close enough together for
# DocumentsApp's redlock (documents:<run_id>:<type>) to actually contend.
#
# A single sequential PATCH cannot reproduce this — this script exists because the second
# request needs to be in flight while the first is still mid-render.
#
# Usage:
#   ./test_concurrent_run_started.sh [run_id]
# Defaults to run 101 on the api-moslem-asaad-1.qa.bringg.com QA namespace.

set -euo pipefail

HOST="https://api-moslem-asaad-1.qa.bringg.com"
RUN_ID="${1:-110}"
TS_A="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
TS_B="$(date -u -v+1S +%Y-%m-%dT%H:%M:%S.000Z 2>/dev/null || date -u -d '+1 second' +%Y-%m-%dT%H:%M:%S.000Z)"

echo "Target: $HOST/automation/run/$RUN_ID"
echo "Trigger A started_at=$TS_A"
echo "Trigger B started_at=$TS_B"
echo

OUT_A="$(mktemp)"
OUT_B="$(mktemp)"

# Launch both requests as background jobs in the same shell so they're issued within
# milliseconds of each other, then wait for both to finish.
curl -sS -X PATCH "$HOST/automation/run/$RUN_ID" \
  -H "Content-Type: application/json" \
  -d "{\"changes\": {\"started_at\": \"$TS_A\"}}" \
  -w "\nHTTP_STATUS:%{http_code}\n" > "$OUT_A" 2>&1 &
PID_A=$!

curl -sS -X PATCH "$HOST/automation/run/$RUN_ID" \
  -H "Content-Type: application/json" \
  -d "{\"changes\": {\"started_at\": \"$TS_B\"}}" \
  -w "\nHTTP_STATUS:%{http_code}\n" > "$OUT_B" 2>&1 &
PID_B=$!

wait "$PID_A" "$PID_B"

echo "=== Trigger A response ==="
cat "$OUT_A"
echo
echo "=== Trigger B response ==="
cat "$OUT_B"
rm -f "$OUT_A" "$OUT_B"

cat <<EOF

Both triggers sent. Now check:
  - Kibana: filter run_id:$RUN_ID — expect TWO "DocumentsApp onRunStarted called" lines,
    exactly one full render+webhook path, and the other either
    "DocumentsApp generateDocument document already stored, skipping" or (if contention
    outlasts Redlock's retry budget) "executeCallback - DocumentsApp - run:started - failed
    with LockError: ...".
  - DB: SELECT * FROM uploads WHERE record_type='Run' AND record_id=$RUN_ID
    AND attachment_type='runAggregation'; — expect exactly ONE row.
  - Webhook debug page — expect exactly ONE new delivery.
EOF
