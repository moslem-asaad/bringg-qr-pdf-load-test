#!/usr/bin/env python3
"""
Aggregates DocumentsApp pipeline outcomes and latency for the stg2 500-parallel
run:started load test (BRNGG-55375), by querying OpenSearch directly over the
Teleport mTLS app proxy (no browser/Kibana needed).

Requires: `tsh app login opensearch-dashboards-stg2` already run once (this
script reads the cert/key tsh wrote under ~/.tsh/keys/...).

Usage:
    python3 load_test_metrics.py --merchant-id 60596 --since now-30m [--until now]
    python3 load_test_metrics.py --merchant-id 60596 --since 2026-09-17T13:00:00Z --until 2026-09-17T13:15:00Z
    python3 load_test_metrics.py --merchant-id 60596 --since now-30m --csv per_run.csv
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import requests

TELEPORT_APP = "opensearch-dashboards-stg2"
TELEPORT_HOST = f"{TELEPORT_APP}.teleport.pme.gcloud.bringg.com"
BASE_URL = f"https://{TELEPORT_HOST}/opensearch-dashboards"
INDEX_PATTERN = "logstash-2*"

# Ordered: first pattern that matches a line's message wins. Order matters where
# substrings could otherwise collide (none currently do, but keep specific-first).
OUTCOME_PATTERNS = [
    ("no_matching_config", "no matching documents_configurations trigger, halting"),
    ("no_tasks", "run has no tasks, halting"),
    ("skipped_already_stored", "document already stored, skipping"),
    ("render_call_failed", "templates-service render call failed"),
    ("render_returned_failure", "templates-service render returned failure"),
    ("lock_failed", "failed with LockError"),
    ("webhook_delivered", "sendWebHook - was done for"),
]
START_MARKER = "DocumentsApp onRunStarted called"

# templates-service's own log line from pdf_renderer.ts's fail(): logger.error(`${LOG_PREFIX} failed`,
# { ...logMeta, params: { reason, detail, status } }). `reason` is one of PdfRenderFailureReason:
# 'asset' | 'content' | 'shed' | 'unavailable' | 'timeout'. 'shed' is the ONLY reason that means "this
# pod refused the work because it hit its own max_waiting gate" (pdf_renderer.ts:264-270) -- i.e. the
# capacity-limit failure. 'unavailable'/'timeout' can also correlate with saturation (Gotenberg itself
# overloaded, or a wedged connection) but are not proof of the max_concurrent/max_waiting gate itself.
RENDER_FAIL_MARKER = "PdfRenderer.renderPdf failed"
CAPACITY_REASON = "shed"


def fetch_render_failures(cert_key, merchant_id, since, until, page_size=1000):
    """Returns {request_id: {reason, detail, status, ts}} from templates-service's own failure log."""
    hits = []
    search_after = None
    while True:
        body = {
            "size": page_size,
            "sort": [{"@timestamp": "asc"}, {"_id": "asc"}],
            "query": {
                "bool": {
                    "must": [{"match_phrase": {"message": RENDER_FAIL_MARKER}}],
                    "filter": [
                        {"term": {"application.keyword": "templates-service"}},
                        {"range": {"@timestamp": {"gte": since, "lte": until}}},
                        {"term": {"merchant_id": merchant_id}},
                    ],
                }
            },
        }
        if search_after:
            body["search_after"] = search_after

        data = opensearch_query(cert_key, body)
        page = data.get("hits", {}).get("hits", [])
        if not page:
            break
        hits.extend(page)
        if len(page) < page_size:
            break
        search_after = page[-1]["sort"]

    by_request_id = {}
    for h in hits:
        src = h["_source"]
        request_id = src.get("request_id")
        if not request_id:
            continue
        raw_params = src.get("params")
        try:
            params = json.loads(raw_params) if isinstance(raw_params, str) else (raw_params or {})
        except (TypeError, ValueError):
            params = {}
        by_request_id[request_id] = {
            "reason": params.get("reason", "unknown"),
            "detail": params.get("detail"),
            "status": params.get("status"),
            "ts": src.get("@timestamp"),
        }
    return by_request_id


def find_tsh_cert_key():
    key_dir = os.path.expanduser("~/.tsh/keys")
    matches = glob.glob(f"{key_dir}/*/*-app/*/{TELEPORT_APP}.crt")
    if not matches:
        sys.exit(
            f"No Teleport cert found for app '{TELEPORT_APP}'.\n"
            f"Run: tsh app login {TELEPORT_APP}"
        )
    cert = matches[0]
    key = cert[: -len(".crt")] + ".key"
    if not os.path.exists(key):
        sys.exit(f"Found cert but no matching key: {key}")
    return cert, key


def opensearch_query(cert_key, body):
    cert, key = cert_key
    resp = requests.post(
        f"{BASE_URL}/api/console/proxy",
        params={"path": f"{INDEX_PATTERN}/_search", "method": "POST"},
        headers={"osd-xsrf": "true", "Content-Type": "application/json"},
        data=json.dumps(body),
        cert=(cert, key),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data and "hits" not in data:
        sys.exit(f"OpenSearch error: {data}")
    return data


def fetch_all_hits(cert_key, merchant_id, since, until, page_size=1000):
    query_strings = [START_MARKER] + [p for _, p in OUTCOME_PATTERNS]
    should = [{"match_phrase": {"message": q}} for q in query_strings]

    hits = []
    search_after = None
    while True:
        body = {
            "size": page_size,
            "sort": [{"@timestamp": "asc"}, {"_id": "asc"}],
            "query": {
                "bool": {
                    "should": should,
                    "minimum_should_match": 1,
                    "filter": [
                        {"range": {"@timestamp": {"gte": since, "lte": until}}},
                        {"term": {"merchant_id": merchant_id}},
                    ],
                }
            },
        }
        if search_after:
            body["search_after"] = search_after

        data = opensearch_query(cert_key, body)
        page = data.get("hits", {}).get("hits", [])
        if not page:
            break
        hits.extend(page)
        if len(page) < page_size:
            break
        search_after = page[-1]["sort"]

    return hits


def classify(message):
    for outcome, pattern in OUTCOME_PATTERNS:
        if pattern in message:
            return outcome
    return None


def to_epoch_ms(ts):
    from datetime import datetime

    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts).timestamp() * 1000


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merchant-id", type=int, required=True)
    ap.add_argument("--since", default="now-30m", help="OpenSearch date-math or ISO8601, e.g. now-30m")
    ap.add_argument("--until", default="now")
    ap.add_argument("--csv", help="Optional path to write a per-run CSV")
    args = ap.parse_args()

    cert_key = find_tsh_cert_key()

    print(f"Querying OpenSearch for merchant_id={args.merchant_id}, {args.since} .. {args.until} ...",
          file=sys.stderr)
    hits = fetch_all_hits(cert_key, args.merchant_id, args.since, args.until)
    print(f"Fetched {len(hits)} matching log lines.", file=sys.stderr)

    render_failures = fetch_render_failures(cert_key, args.merchant_id, args.since, args.until)
    print(f"Fetched {len(render_failures)} templates-service render-failure log lines.", file=sys.stderr)

    runs = defaultdict(lambda: {"start_ts": None, "outcome": None, "outcome_ts": None, "request_id": None})

    for h in hits:
        src = h["_source"]
        run_id = src.get("run_id")
        if run_id is None:
            continue
        message = src.get("message", "")
        ts = src.get("@timestamp")

        if START_MARKER in message:
            if runs[run_id]["start_ts"] is None:
                runs[run_id]["start_ts"] = ts
                runs[run_id]["request_id"] = src.get("request_id")
            continue

        outcome = classify(message)
        if outcome and runs[run_id]["outcome"] is None:
            runs[run_id]["outcome"] = outcome
            runs[run_id]["outcome_ts"] = ts

    total_runs = len(runs)
    outcome_counts = defaultdict(int)
    latencies_ms = defaultdict(list)
    no_terminal_event = 0

    per_run_rows = []
    for run_id, info in runs.items():
        outcome = info["outcome"] or "no_terminal_event_seen"
        if info["outcome"] is None:
            no_terminal_event += 1
        outcome_counts[outcome] += 1

        latency_ms = None
        if info["start_ts"] and info["outcome_ts"]:
            latency_ms = to_epoch_ms(info["outcome_ts"]) - to_epoch_ms(info["start_ts"])
            latencies_ms[outcome].append(latency_ms)

        render_fail_reason = None
        rf = render_failures.get(info["request_id"])
        if rf:
            render_fail_reason = rf["reason"]

        per_run_rows.append(
            (run_id, info["start_ts"], outcome, info["outcome_ts"], latency_ms, render_fail_reason)
        )

    print("\n=== Outcome breakdown ===")
    print(f"{'outcome':30s} {'count':>6s} {'% of runs':>10s}")
    for outcome, count in sorted(outcome_counts.items(), key=lambda kv: -kv[1]):
        pct = 100 * count / total_runs if total_runs else 0
        print(f"{outcome:30s} {count:6d} {pct:9.1f}%")
    print(f"\nTotal runs observed (with a start marker or terminal event): {total_runs}")

    print("\n=== Latency (ms) from 'onRunStarted called' to terminal log line, per outcome ===")
    print(f"{'outcome':30s} {'n':>5s} {'p50':>8s} {'p95':>8s} {'p99':>8s} {'max':>8s}")
    for outcome, vals in latencies_ms.items():
        vals_sorted = sorted(vals)
        p50 = percentile(vals_sorted, 50)
        p95 = percentile(vals_sorted, 95)
        p99 = percentile(vals_sorted, 99)
        vmax = vals_sorted[-1]
        print(f"{outcome:30s} {len(vals):5d} {p50:8.0f} {p95:8.0f} {p99:8.0f} {vmax:8.0f}")

    reason_counts = defaultdict(int)
    unmatched_failures = 0
    for run_id, info in runs.items():
        if info["outcome"] not in ("render_call_failed", "render_returned_failure"):
            continue
        rf = render_failures.get(info["request_id"])
        if rf:
            reason_counts[rf["reason"]] += 1
        else:
            # The RPC-level failure never got a matching templates-service log line -- e.g. it never
            # reached templates-service at all (transport-level timeout on the hagmonia-js side).
            reason_counts["no_matching_templates_service_log"] += 1
            unmatched_failures += 1

    total_render_failures = sum(reason_counts.values())
    print("\n=== templates-service render failure reasons (PdfRenderFailureReason) ===")
    if total_render_failures == 0:
        print("No render_call_failed / render_returned_failure runs in this window.")
    else:
        print(f"{'reason':35s} {'count':>6s} {'% of render failures':>22s}")
        for reason, count in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
            pct = 100 * count / total_render_failures
            flag = "  <-- capacity gate (max_waiting exceeded)" if reason == CAPACITY_REASON else ""
            print(f"{reason:35s} {count:6d} {pct:21.1f}%{flag}")

        shed_count = reason_counts.get(CAPACITY_REASON, 0)
        print(
            f"\n{shed_count} of {total_render_failures} render failures ({100 * shed_count / total_render_failures:.1f}%) "
            f"were '{CAPACITY_REASON}' -- pdf_renderer.ts's own gate rejecting work because "
            "`limit.pendingCount >= pdf_renderer.max_waiting` (pdf_renderer.ts:261-270). This is the direct "
            "signal for whether max_concurrent/max_waiting are undersized for this load, separate from "
            "'unavailable' (Gotenberg itself failing work it accepted) or 'timeout' (a wedged connection)."
        )
        if unmatched_failures:
            print(
                f"\nNote: {unmatched_failures} render failure(s) had no matching templates-service log line "
                "-- the request likely never reached templates-service at all (e.g. the RPC call itself "
                "timed out on the hagmonia-js side). These are NOT counted as 'shed' since we can't confirm "
                "the reason, but under heavy load they're also consistent with templates-service being "
                "saturated -- worth cross-checking RabbitMQ/RPC queue depth for the same window."
            )

    if no_terminal_event:
        print(
            f"\n{no_terminal_event} run(s) have a start marker but no terminal log line in this window "
            "(still in flight, or terminal line fell outside --until, or the success path produced no "
            "further DocumentsApp/webhook log at all and the webhook send is still pending)."
        )

    if args.csv:
        import csv

        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["run_id", "started_at", "outcome", "outcome_at", "latency_ms", "render_fail_reason"])
            for row in sorted(per_run_rows, key=lambda r: (r[1] or "")):
                w.writerow(row)
        print(f"\nPer-run detail written to {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
