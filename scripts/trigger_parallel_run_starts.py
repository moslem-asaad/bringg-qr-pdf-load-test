#!/usr/bin/env python3
"""
Fires `POST /api/tasks/:id/start` concurrently for many seeded stg2 drivers, to trigger
their run's `run:started` event roughly in parallel (BRNGG-55375's 500-parallel load test).

Each driver only needs ONE of their run's tasks started to fire `run:started` for that run
(the other task on the same run does not need a separate start call).

Inputs (already seeded by an earlier session, read-only here):
  - stg2_500_drivers_tokens.csv  (user_id,name,external_id,email,token,status)
  - stg2_reassign_new_drivers_log.csv  (run_idx,run_ext,driver_id,task_id,status,ok,run_id,task_user_id)

Usage:
    # Small test batch first (recommended) -- confirms no rate limit on this endpoint:
    python3 trigger_parallel_run_starts.py --limit 20 --workers 20 --out test_batch.csv

    # Full 500-parallel run:
    python3 trigger_parallel_run_starts.py --workers 100 --out full_run.csv
"""
import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

TOKENS_CSV = "/private/tmp/claude-501/-Users-moslemasaad-bringg/2c92e327-422e-4e77-a530-4aa783623375/scratchpad/stg2_500_drivers_tokens.csv"
REASSIGN_CSV = "/private/tmp/claude-501/-Users-moslemasaad-bringg/2d405642-f89b-43b8-a0da-3f3a23da86f9/scratchpad/stg2_reassign_new_drivers_log.csv"
START_URL_TMPL = "https://stg2-api.bringg.com/api/tasks/{task_id}/start"


def load_driver_tokens():
    with open(TOKENS_CSV, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "ok"]
    return {int(r["user_id"]): r["token"] for r in rows}


def load_driver_first_task():
    """One task per driver_id -- the lowest task_id seen (either task on the run works to
    trigger run:started; picking deterministically makes reruns/debugging easier)."""
    by_driver = OrderedDict()
    with open(REASSIGN_CSV, newline="") as f:
        for r in csv.DictReader(f):
            driver_id = int(r["driver_id"])
            task_id = int(r["task_id"])
            if driver_id not in by_driver or task_id < by_driver[driver_id]:
                by_driver[driver_id] = task_id
    return by_driver


def start_task(driver_id, task_id, token, timeout_s):
    url = START_URL_TMPL.format(task_id=task_id)
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "authorization": f"Token token={token}",
            "client": "iOS",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            status_code = resp.status
    except urllib.error.HTTPError as e:
        status_code = e.code
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"error": f"HTTP {e.code}"}
    except Exception as e:
        status_code = None
        body = {"error": str(e)}
    elapsed_ms = round((time.time() - t0) * 1000)

    run_id = None
    task = body.get("task") if isinstance(body, dict) else None
    if isinstance(task, dict):
        run_id = task.get("run_id")

    return {
        "driver_id": driver_id,
        "task_id": task_id,
        "http_status": status_code,
        "success": bool(body.get("success")) if isinstance(body, dict) else False,
        "run_id": run_id,
        "elapsed_ms": elapsed_ms,
        "error": None if (isinstance(body, dict) and body.get("success")) else json.dumps(body)[:300],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="Only fire the first N drivers (for a test batch)")
    ap.add_argument("--workers", type=int, default=50, help="Concurrent worker threads")
    ap.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout (s)")
    ap.add_argument("--out", required=True, help="CSV path to write per-driver results")
    args = ap.parse_args()

    tokens = load_driver_tokens()
    tasks_by_driver = load_driver_first_task()

    drivers = [(d, t) for d, t in tasks_by_driver.items() if d in tokens]
    if args.limit:
        drivers = drivers[: args.limit]

    print(f"Firing {len(drivers)} task starts with {args.workers} workers...", file=sys.stderr)
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"started_at (UTC): {started_at}", file=sys.stderr)

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(start_task, driver_id, task_id, tokens[driver_id], args.timeout): (driver_id, task_id)
            for driver_id, task_id in drivers
        }
        done = 0
        for fut in as_completed(futures):
            driver_id, task_id = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {
                    "driver_id": driver_id,
                    "task_id": task_id,
                    "http_status": None,
                    "success": False,
                    "run_id": None,
                    "elapsed_ms": None,
                    "error": str(e),
                }
            results.append(r)
            done += 1
            status_str = "ok" if r["success"] else f"FAILED ({r['http_status']}: {r['error']})"
            print(f"[{done}/{len(drivers)}] driver={r['driver_id']} task={r['task_id']} "
                  f"run={r['run_id']} {r['elapsed_ms']}ms -> {status_str}", flush=True)

    ended_at = datetime.now(timezone.utc).isoformat()
    print(f"ended_at (UTC): {ended_at}", file=sys.stderr)

    ok_count = sum(1 for r in results if r["success"])
    print(f"\nDone. {ok_count}/{len(results)} succeeded.", file=sys.stderr)
    print(f"Feed this window into load_test_metrics.py: --since {started_at} --until {ended_at}", file=sys.stderr)

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["driver_id", "task_id", "http_status", "success", "run_id", "elapsed_ms", "error"])
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(f"Per-driver results written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
