#!/usr/bin/env python3
"""
fetch_grafana_metrics.py — Pull Gotenberg metrics from Grafana and patch the load test reports.

Usage:
    python3 fetch_grafana_metrics.py \
        --meta test-data/rate_baseline_2026-09-24T10-00_meta.json \
        --env  stg2

Auth (Teleport session cookies — copy from browser DevTools → Application → Cookies):
    export GRAFANA_SESSION="<__Host-grv_app_session value>"
    export GRAFANA_SESSION_SUBJECT="<__Host-grv_app_session_subject value>"

The script patches _report.md and _report.html in-place with real Gotenberg numbers.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

GRAFANA_HOST  = "https://grafana-pme.teleport.pme.gcloud.bringg.com"
DATASOURCE_UID = "DF2B96xnk"  # Thanos (default)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--meta", required=True,
                   help="Path to _meta.json written by the k6 run")
    p.add_argument("--env", default="stg2",
                   help="Grafana environment label (default: stg2)")
    return p.parse_args()


def get_cookies():
    session = os.environ.get("GRAFANA_SESSION")
    subject = os.environ.get("GRAFANA_SESSION_SUBJECT")
    if not session or not subject:
        print("ERROR: set GRAFANA_SESSION and GRAFANA_SESSION_SUBJECT env vars.", file=sys.stderr)
        sys.exit(1)
    return f"__Host-grv_app_session={session}; __Host-grv_app_session_subject={subject}"


def query_grafana(expr, start_ms, end_ms, cookie, step="60"):
    """Query Grafana /api/ds/query and return list of (timestamps, values) frames."""
    url = f"{GRAFANA_HOST}/api/ds/query"
    body = json.dumps({
        "queries": [{
            "datasource": {"uid": DATASOURCE_UID},
            "expr":       expr,
            "range":      True,
            "refId":      "A",
            "step":       step,
            "maxDataPoints": 1000,
        }],
        "from": str(start_ms),
        "to":   str(end_ms),
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Cookie":        cookie,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  Grafana HTTP {e.code} for query: {expr[:80]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Grafana error: {e}", file=sys.stderr)
        return None


def extract_values(result):
    """Return flat list of float values from a Grafana query result."""
    if not result:
        return []
    try:
        frames = result["results"]["A"]["frames"]
        values = []
        for frame in frames:
            vals = frame["data"]["values"]
            if len(vals) >= 2:
                values.extend([v for v in vals[1] if v is not None])
        return values
    except (KeyError, IndexError, TypeError):
        return []


def safe_avg(vals):
    return sum(vals) / len(vals) if vals else None

def safe_max(vals):
    return max(vals) if vals else None

def fmt(v, unit=""):
    if v is None:
        return "—"
    if unit == "cores":
        return f"{v:.3f}"
    if unit == "MB":
        return f"{v / 1_048_576:.1f}"
    return f"{v:.1f}"


def fetch_metrics(start_ms, end_ms, env, cookie):
    env_filter = f'environment="{env}"'

    print("  Fetching CPU...", file=sys.stderr)
    cpu_result = query_grafana(
        f'sum(rate(container_cpu_usage_seconds_total{{{env_filter},container="gotenberg"}}[1m]))',
        start_ms, end_ms, cookie,
    )
    cpu_vals = extract_values(cpu_result)

    print("  Fetching memory...", file=sys.stderr)
    mem_result = query_grafana(
        f'sum(container_memory_working_set_bytes{{{env_filter},container="gotenberg"}})',
        start_ms, end_ms, cookie,
    )
    mem_vals = extract_values(mem_result)

    print("  Fetching Chromium queue...", file=sys.stderr)
    queue_result = query_grafana(
        f'max(gotenberg_chromium_requests_queue_size{{{env_filter}}})',
        start_ms, end_ms, cookie, step="15",
    )
    queue_vals = extract_values(queue_result)

    print("  Fetching Chromium restarts...", file=sys.stderr)
    restart_result = query_grafana(
        f'sum(increase(gotenberg_chromium_restarts_count{{{env_filter}}}[1h]))',
        start_ms, end_ms, cookie,
    )
    restart_vals = extract_values(restart_result)

    return {
        "cpu_max":       fmt(safe_max(cpu_vals), "cores"),
        "mem_max_mb":    fmt(safe_max(mem_vals), "MB"),
        "queue_max":     fmt(safe_max(queue_vals)),
        "restarts":      fmt(safe_max(restart_vals)),
        "_cpu_samples":  len(cpu_vals),
        "_mem_samples":  len(mem_vals),
        "_queue_samples": len(queue_vals),
    }


def patch_md(path, m):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    replacements = {
        r"\| CPU max \(cores\) \|.*\|":    f"| CPU max (cores) | {m['cpu_max']} |",
        r"\| Memory max \(MB\) \|.*\|":    f"| Memory max (MB) | {m['mem_max_mb']} |",
        r"\| Chromium queue peak \|.*\|":   f"| Chromium queue peak | {m['queue_max']} |",
        r"\| Chromium restarts \|.*\|":     f"| Chromium restarts | {m['restarts']} |",
    }
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  Patched {path}", file=sys.stderr)


def patch_html(path, m):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    rows = {
        "CPU max (cores)":      m["cpu_max"],
        "Memory max (MB)":      m["mem_max_mb"],
        "Chromium queue peak":  m["queue_max"],
        "Chromium restarts":    m["restarts"],
    }
    for label, val in rows.items():
        text = re.sub(
            rf'(<td>{re.escape(label)}</td><td>)[^<]*(</td>)',
            rf'\g<1>{val}\g<2>',
            text,
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  Patched {path}", file=sys.stderr)


def main():
    args = parse_args()
    cookie = get_cookies()

    with open(args.meta, encoding="utf-8") as f:
        meta = json.load(f)

    scenario   = meta["scenario"]
    suffix     = meta["suffix"]
    start_ms   = int(meta["testStartMs"])
    end_ms     = int(meta["testEndMs"])

    print(f"Fetching Gotenberg metrics for {scenario} ({suffix})", file=sys.stderr)
    print(f"  Window: {start_ms} → {end_ms} ({(end_ms - start_ms) // 1000}s)", file=sys.stderr)

    m = fetch_metrics(start_ms, end_ms, args.env, cookie)

    print(f"\nGotenberg results:", file=sys.stderr)
    print(f"  CPU max:     {m['cpu_max']} ({m['_cpu_samples']} samples)", file=sys.stderr)
    print(f"  Memory max:  {m['mem_max_mb']} MB ({m['_mem_samples']} samples)", file=sys.stderr)
    print(f"  Queue peak:  {m['queue_max']} ({m['_queue_samples']} samples)", file=sys.stderr)
    print(f"  Restarts:    {m['restarts']}", file=sys.stderr)

    base = f"test-data/rate_{scenario}_{suffix}"
    for ext, fn in [("_report.md", patch_md), ("_report.html", patch_html)]:
        path = base + ext
        if os.path.exists(path):
            fn(path, m)
        else:
            print(f"  WARNING: {path} not found, skipping", file=sys.stderr)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
