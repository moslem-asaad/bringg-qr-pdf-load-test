#!/usr/bin/env python3
"""
SETUP ONLY -- accepts (POST /api/tasks/:id/accept) each k6c run's primary task,
so the parallel k6 /start burst can succeed. Does NOT call /start on anything.

Input:  test-data/k6c_runs_parsed.json
        test-data/k6b_driver_tokens.csv (same drivers 68514-68563)
Output: test-data/k6c_runs_with_tokens.json  (direct input to load_test_50_parallel.js)

Usage:
    cd scripts && python3 accept_k6c_tasks.py
"""
import csv
import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "https://stg2-api.bringg.com"
RUNS_FILE = "test-data/k6c_runs_parsed.json"
TOKENS_FILES = ["test-data/k6b_driver_tokens.csv", "test-data/k6_driver_tokens.csv", "test-data/k6_retry_tokens.csv"]
OUT_FILE = "test-data/k6c_runs_with_tokens.json"


def call(path, token):
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=b"", method="POST",
        headers={"Content-Type": "application/json", "authorization": f"Token token={token}", "client": "iOS"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"error": "unparsable"}
    except Exception as e:
        return None, {"error": str(e)}


def main():
    with open(RUNS_FILE) as f:
        runs = json.load(f)

    tokens = {}
    for tf in TOKENS_FILES:
        try:
            with open(tf) as f:
                for r in csv.DictReader(f):
                    uid = int(r["user_id"])
                    if r["status"] == "ok" and r["token"] and uid not in tokens:
                        tokens[uid] = r["token"]
        except FileNotFoundError:
            pass

    print(f"{len(runs)} runs, {len(tokens)} driver tokens available", file=sys.stderr)

    ready = []
    for i, run in enumerate(runs, start=1):
        driver_id = run["driver_id"]
        task_id = run["primary_task_id"]
        token = tokens.get(driver_id)

        if not token:
            print(f"[{i}/{len(runs)}] run={run['run_id']} driver={driver_id} -> SKIPPED, no token", flush=True)
            continue

        status, body = call(f"/api/tasks/{task_id}/accept", token)
        task_status = body.get("task", {}).get("status") if isinstance(body, dict) else None
        accepted = isinstance(body, dict) and body.get("success") and task_status == 6
        already = task_status == 6  # already accepted

        print(f"[{i}/{len(runs)}] run={run['run_id']} ({run['run_external_id']}) driver={driver_id} "
              f"task={task_id} http={status} accepted={accepted}", flush=True)

        if accepted or already:
            ready.append({**run, "token": token})

        time.sleep(0.15)

    with open(OUT_FILE, "w") as f:
        json.dump(ready, f, indent=2)

    print(f"\nDone. {len(ready)}/{len(runs)} runs accepted and ready.", file=sys.stderr)
    print(f"Written to {OUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
