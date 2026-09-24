#!/usr/bin/env python3
"""
Accept all primary tasks for a rate-based load test batch and write an
interleaved-by-driver JSON file that load_test_rate.js reads.

What "interleaved by driver" means:
  tasks[0] = driver_A, task_1
  tasks[1] = driver_B, task_1
  ...
  tasks[N-1] = driver_N, task_1
  tasks[N]   = driver_A, task_2
  ...

  With this ordering, iterationInTest % tasks.length assigns consecutive
  iteration IDs to different drivers, so no two concurrent VUs share a
  driver — preventing "driver already in an open run" collisions.

Usage:
    cd scripts
    python3 accept_rate_tasks.py \\
        --runs   test-data/rate_k6e_runs_parsed.json \\
        --tokens test-data/k6b_driver_tokens.csv \\
        --output test-data/rate_k6e_tasks.json

Input (--runs):   output of parse_runs_csv.py — array of:
    {run_id, run_external_id, driver_id, primary_task_id, all_task_ids}

Input (--tokens): driver login tokens CSV with columns:
    user_id,token,status   (status=ok means usable)

Output (--output): JSON array of tasks sorted round-robin by driver,
    each entry: {run_id, run_external_id, driver_id, primary_task_id, token}
    — direct input to load_test_rate.js (TASKS_FILE env var).
"""

import argparse
import concurrent.futures
import csv
import json
import sys
import threading
import time
import urllib.error
import urllib.request

BASE_URL = "https://stg2-api.bringg.com"
ACCEPT_DELAY_S = 0.15   # used only when --workers 1


def call_accept(task_id, token, max_retries=4):
    """POST /accept. Retries HTTP 429 with exponential backoff (2, 4, 8, 16s)."""
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            f"{BASE_URL}/api/tasks/{task_id}/accept",
            data=b"", method="POST",
            headers={
                "Content-Type": "application/json",
                "authorization": f"Token token={token}",
                "client": "iOS",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                body = {"error": "unparsable"}
            if e.code == 429 and attempt < max_retries:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            return e.code, body
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2)
                continue
            return None, {"error": str(e)}
    return 429, {"error": "rate limited"}


def interleave_by_driver(ready):
    """Sort tasks in round-robin order by driver_id."""
    by_driver = {}
    for t in ready:
        by_driver.setdefault(t["driver_id"], []).append(t)

    drivers    = sorted(by_driver.keys())
    max_tasks  = max(len(v) for v in by_driver.values())
    result     = []
    for i in range(max_tasks):
        for d in drivers:
            tasks = by_driver[d]
            if i < len(tasks):
                result.append(tasks[i])
    return result


def load_tokens(*paths):
    tokens = {}
    for path in paths:
        try:
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    uid = int(row["user_id"])
                    if row.get("status") == "ok" and row.get("token") and uid not in tokens:
                        tokens[uid] = row["token"]
        except FileNotFoundError:
            pass
    return tokens


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs",   required=True,
                    help="Parsed runs JSON (output of parse_runs_csv.py)")
    ap.add_argument("--tokens", nargs="+",
                    default=["test-data/k6b_driver_tokens.csv",
                             "test-data/k6_driver_tokens.csv",
                             "test-data/rate_driver_tokens.csv"],
                    help="One or more driver-token CSV files")
    ap.add_argument("--output", required=True,
                    help="Output tasks JSON for load_test_rate.js")
    ap.add_argument("--skip-accept", action="store_true",
                    help="Skip HTTP calls (use if tasks are already accepted); just interleave and write")
    ap.add_argument("--workers", type=int, default=8,
                    help="Parallel accept workers (default: 8). Use 1 for the old sequential pace.")
    args = ap.parse_args()

    with open(args.runs) as f:
        runs = json.load(f)

    tokens = load_tokens(*args.tokens)
    print(f"{len(runs)} runs, {len(tokens)} driver tokens available, workers={args.workers}",
          file=sys.stderr)

    ready = []
    ready_lock = threading.Lock()
    progress = 0
    progress_lock = threading.Lock()
    total = len(runs)

    def accept_one(i_run):
        i, run = i_run
        driver_id = run["driver_id"]
        task_id   = run["primary_task_id"]
        token     = tokens.get(driver_id)

        if not token:
            print(f"[{i}/{total}] run={run['run_id']} ({run['run_external_id']}) "
                  f"driver={driver_id} → SKIPPED (no token)", flush=True)
            return

        if args.skip_accept:
            accepted = True
            status = "skip"
            print(f"[{i}/{total}] {run['run_external_id']} driver={driver_id} "
                  f"task={task_id} SKIP_ACCEPT=True", flush=True)
        else:
            status, body = call_accept(task_id, token)
            task_status  = body.get("task", {}).get("status") if isinstance(body, dict) else None
            accepted     = isinstance(body, dict) and (
                (body.get("success") and task_status == 6) or task_status == 6
            )
            print(f"[{i}/{total}] {run['run_external_id']} driver={driver_id} "
                  f"task={task_id} http={status} accepted={accepted}", flush=True)
            if args.workers <= 1:
                time.sleep(ACCEPT_DELAY_S)

        if accepted:
            with ready_lock:
                ready.append({
                    "run_id":           run["run_id"],
                    "run_external_id":  run["run_external_id"],
                    "driver_id":        driver_id,
                    "primary_task_id":  task_id,
                    "token":            token,
                })

        nonlocal progress
        with progress_lock:
            progress += 1
            if progress % 500 == 0 or progress == total:
                print(f"  progress {progress}/{total}", flush=True)

    indexed = list(enumerate(runs, start=1))
    if args.workers <= 1 or args.skip_accept:
        for item in indexed:
            accept_one(item)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(accept_one, indexed))

    interleaved = interleave_by_driver(ready)

    with open(args.output, "w") as f:
        json.dump(interleaved, f, indent=2)

    n_drivers = len({t["driver_id"] for t in interleaved})
    print(f"\nDone. {len(interleaved)} tasks accepted across {n_drivers} drivers.", file=sys.stderr)
    print(f"Written to {args.output} (interleaved round-robin by driver)", file=sys.stderr)
    print(f"\nCapacity check:", file=sys.stderr)
    print(f"  Tasks available:    {len(interleaved)}", file=sys.stderr)
    print(f"  soak  (30/s × 25min):  need 45 000 — {'OK' if len(interleaved) >= 45000 else 'INSUFFICIENT'}", file=sys.stderr)
    print(f"  spike (150/s × 1min):  need  9 000 — {'OK' if len(interleaved) >= 9000 else 'INSUFFICIENT'}", file=sys.stderr)


if __name__ == "__main__":
    main()
