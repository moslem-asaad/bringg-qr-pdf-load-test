#!/usr/bin/env python3
"""
Pulls PDF-rendering-pipeline + RabbitMQ metrics from stg2 Grafana's Prometheus
datasource for a given time window, to accompany a k6 load-test run.

Covers: Gotenberg CPU/memory, templates-service CPU/memory, and RabbitMQ
queue depth/consumers/rates for the `templates-service` and `background tasks`
queues (the two queues in this pipeline: hagmonia -> background-tasks
consumes run:started -> RPCs templates-service -> templates-service consumes
the render request).

Requires: `tsh app login grafana-stg2` already run (cert auto-refreshes hourly,
rerun that command if you see a 403/SSL error).

Usage:
    python3 pull_pipeline_metrics.py --since 2026-09-22T12:00:00Z --until 2026-09-22T12:05:00Z
    python3 pull_pipeline_metrics.py --since now-10m --until now
"""
import argparse
import glob
import json
import os
import re
import sys
import time

import requests


def resolve_time(spec):
    """Resolve a Grafana-style time spec ('now', 'now-15m', RFC3339, or a raw
    unix timestamp) to a unix timestamp, since the raw Prometheus HTTP API
    (unlike Grafana's own UI) does not understand 'now-Xm' relative syntax."""
    if spec == "now":
        return time.time()
    m = re.fullmatch(r"now-(\d+)([smhd])", spec)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return time.time() - n * seconds
    try:
        return float(spec)
    except ValueError:
        pass
    # Assume RFC3339 / ISO8601
    from datetime import datetime

    return datetime.fromisoformat(spec.replace("Z", "+00:00")).timestamp()

TELEPORT_APP = "grafana-stg2"
BASE_URL = f"https://{TELEPORT_APP}.teleport.pme.gcloud.bringg.com"
PROM_UID = "000000001"

# Pods matched by regex against kube_pod_container_info / container_* metrics.
GOTENBERG_POD_RE = "gotenberg-.*"
TEMPLATES_SERVICE_POD_RE = "templates-service-[0-9a-f]+-.*"

# RabbitMQ queues relevant to this pipeline (confirmed present in stg2 Prometheus
# via `rabbitmq_queue_messages_ready`'s `queue` label -- reverify if queue
# naming changes):
#   "background tasks"  -- hagmonia-js's background-tasks consumer (DocumentsApp
#                           lives here, consumes run:started)
#   "templates-service"  -- templates-service's own RPC consumer queue
RABBITMQ_QUEUES = ["background tasks", "templates-service"]


def find_tsh_cert_key():
    key_dir = os.path.expanduser("~/.tsh/keys")
    matches = glob.glob(f"{key_dir}/*/*-app/*/{TELEPORT_APP}.crt")
    if not matches:
        sys.exit(f"No Teleport cert for '{TELEPORT_APP}'. Run: tsh app login {TELEPORT_APP}")
    cert = matches[0]
    key = cert[: -len(".crt")] + ".key"
    return cert, key


def prom_query_range(cert_key, query, start, end, step="15s"):
    cert, key = cert_key
    resp = requests.get(
        f"{BASE_URL}/api/datasources/proxy/uid/{PROM_UID}/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "step": step},
        cert=(cert, key),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def prom_query_instant(cert_key, query, time=None):
    cert, key = cert_key
    params = {"query": query}
    if time:
        params["time"] = time
    resp = requests.get(
        f"{BASE_URL}/api/datasources/proxy/uid/{PROM_UID}/api/v1/query",
        params=params,
        cert=(cert, key),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def series_min_max(data):
    vals = []
    for r in data.get("data", {}).get("result", []):
        vals.extend(float(v[1]) for v in r["values"])
    if not vals:
        return None, None
    return min(vals), max(vals)


def to_mib(bytes_val):
    return bytes_val / 1048576 if bytes_val is not None else None


def report_resource(cert_key, label, pod_re, since, until):
    mem = prom_query_range(cert_key, f'container_memory_working_set_bytes{{pod=~"{pod_re}"}}', since, until)
    cpu = prom_query_range(cert_key, f'rate(container_cpu_usage_seconds_total{{pod=~"{pod_re}"}}[30s])', since, until)
    mem_min, mem_max = series_min_max(mem)
    cpu_min, cpu_max = series_min_max(cpu)
    print(f"\n=== {label} ===")
    if mem_max is not None:
        print(f"  memory: {to_mib(mem_min):.1f} - {to_mib(mem_max):.1f} MiB")
    else:
        print("  memory: no data (pod may not have existed in this window -- check the pod regex/time range)")
    if cpu_max is not None:
        print(f"  cpu:    {cpu_min:.3f} - {cpu_max:.3f} cores")
    else:
        print("  cpu:    no data")


def report_rabbitmq(cert_key, since, until):
    print("\n=== RabbitMQ ===")
    for queue in RABBITMQ_QUEUES:
        print(f"\n  -- queue: {queue!r} --")
        metrics = {
            "messages_ready (queue depth)": f'rabbitmq_queue_messages_ready{{queue="{queue}"}}',
            "messages_unacknowledged": f'rabbitmq_queue_messages_unacknowledged{{queue="{queue}"}}',
            "consumers": f'rabbitmq_queue_consumers{{queue="{queue}"}}',
            "publish_rate (msg/s)": f'rabbitmq_queue_messages_publish_rate{{queue="{queue}"}}',
            "deliver_rate (msg/s)": f'rabbitmq_queue_messages_deliver_rate{{queue="{queue}"}}',
        }
        for label, query in metrics.items():
            data = prom_query_range(cert_key, query, since, until, step="10s")
            vmin, vmax = series_min_max(data)
            if vmax is None:
                print(f"    {label:35s} no data")
            else:
                print(f"    {label:35s} {vmin:.2f} - {vmax:.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="Prometheus time (RFC3339 or 'now-Xm')")
    ap.add_argument("--until", required=True)
    args = ap.parse_args()

    cert_key = find_tsh_cert_key()

    since_ts = resolve_time(args.since)
    until_ts = resolve_time(args.until)

    print(f"Pipeline metrics for stg2, window {args.since} .. {args.until} "
          f"({since_ts:.0f} .. {until_ts:.0f})", file=sys.stderr)

    report_resource(cert_key, "Gotenberg", GOTENBERG_POD_RE, since_ts, until_ts)
    report_resource(cert_key, "templates-service", TEMPLATES_SERVICE_POD_RE, since_ts, until_ts)
    report_rabbitmq(cert_key, since_ts, until_ts)


if __name__ == "__main__":
    main()
