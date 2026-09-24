#!/usr/bin/env python3
"""
SETUP ONLY -- accepts (POST /api/tasks/:id/accept) each run's primary task, so
the parallel k6 /start burst can succeed. Does NOT call /start on anything.

Input: test-data/k6b_runs_parsed.json (run_id, run_external_id, driver_id,
primary_task_id, all_task_ids) + test-data/k6b_driver_tokens.csv (driver login
tokens). Produces test-data/k6b_runs_with_tokens.json, the direct input to
load_test_50_parallel.js.

Usage:
    python3 accept_tasks.py
"""
import csv
import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "https://stg2-api.bringg.com"
RUNS_FILE = "test-data/k6b_runs_parsed.json"
# Reusing tokens from the earlier k6 batch this session -- same driver range
# (68514-68563), still valid.
TOKENS_FILES = ["test-data/k6_driver_tokens.csv", "test-data/k6_retry_tokens.csv"]
OUT_FILE = "test-data/k6b_runs_with_tokens.json"


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
        with open(tf) as f:
            for r in csv.DictReader(f):
                if r["status"] == "ok" and r["token"]:
                    tokens[int(r["user_id"])] = r["token"]

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
        accepted = isinstance(body, dict) and body.get("success") and body.get("task", {}).get("status") == 6

        print(f"[{i}/{len(runs)}] run={run['run_id']} ({run['run_external_id']}) driver={driver_id} "
              f"task={task_id} accepted={accepted}", flush=True)

        if accepted:
            ready.append({**run, "token": token})

        time.sleep(0.2)

    with open(OUT_FILE, "w") as f:
        json.dump(ready, f, indent=2)

    print(f"\nDone. {len(ready)}/{len(runs)} runs accepted and ready for the k6 /start burst.", file=sys.stderr)
    print(f"Written to {OUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
