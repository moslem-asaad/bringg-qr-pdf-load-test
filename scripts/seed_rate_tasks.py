#!/usr/bin/env python3
"""
Bulk-create runs and tasks for rate-based load tests (BRNGG-55375).

Reads a driver CSV and a task template JSON, then creates N runs (one per
driver per cycle) with M tasks each, respecting the ~9 req/s per-merchant
rate limit on the services API.  Task creation is parallelised across 8
workers; all creates are completed before the run-assignment pass begins.

Usage:
    cd scripts
    python3 seed_rate_tasks.py \\
        --drivers test-data/rate_drivers.csv \\
        --template rate_task_template.json \\
        --prefix MA-STG2-RATE-K6E \\
        --count 70 \\
        --runs-per-driver 1 \\
        --output test-data/rate_k6e_run_task_mapping.csv

    # For soak (45 000 tasks ≈ 15 000 runs, 70 drivers × ~215 runs each):
    python3 seed_rate_tasks.py \\
        --prefix MA-STG2-SOAK-K6E \\
        --count 70 \\
        --runs-per-driver 215 \\
        --output test-data/soak_k6e_run_task_mapping.csv

Config (top of this file):
    BASE_URL        stg2 API base
    MERCHANT_ID     Bringg merchant/company id
    TEAM_ID         team the tasks are assigned to
    RATE_LIMIT_RPS  max requests per second across all workers (default: 8,
                    safely under the ~9 req/s merchant limit)
    MAX_WORKERS     thread-pool size for concurrent task creation (default: 8)

Output CSV format (compatible with parse_runs_csv.py):
    run_id,run_external_id,driver_id,task_ids
    ,MA-STG2-RATE-K6E-001,68514,"9750001,9750002,9750003"

Notes:
- run_id is left empty and filled later via Redash / parse_runs_csv.py.
- At 8 req/s with 8 workers, each worker fires one request per second.
  Creating 15 000 runs × 3 tasks = 45 000 task creates takes ~1.6 hours
  (down from 5.5 hours with the sequential version).
- The rate limit is per merchant; other tests on merchant 60596 running in
  parallel will reduce your effective budget.
- For a canary: run with --count 1 --runs-per-driver 1 and verify before bulk.

API reference:
  Task create:  POST  /tasks
  Run-assign:   PATCH /tasks/:id  body: {"task": {"run": {"external_id": "..."}}}
"""

import argparse
import concurrent.futures
import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

BASE_URL       = "https://stg2-api.bringg.com"
MERCHANT_ID    = 60596
TEAM_ID        = 103769
RATE_LIMIT_RPS = 8   # stay under the ~9 req/s merchant limit
MAX_WORKERS    = 8   # concurrent threads for task creation

# ── rate limiter (token bucket, thread-safe) ──────────────────────────────────

class RateLimiter:
    """
    Thread-safe token-bucket rate limiter.

    Each call to acquire() blocks until a request slot is available, then
    returns immediately.  Tokens refill at `rps` per second; the bucket never
    accumulates more than `burst` tokens so bursts are bounded.
    """

    def __init__(self, rps: float, burst=None):
        self._interval = 1.0 / rps
        self._burst    = burst or max(1, int(rps))
        self._tokens   = float(self._burst)
        self._last     = time.monotonic()
        self._lock     = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                # refill tokens since last call
                elapsed = now - self._last
                self._tokens = min(self._burst, self._tokens + elapsed * (1.0 / self._interval))
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_for = (1.0 - self._tokens) * self._interval
            time.sleep(wait_for)


# ── progress counter (thread-safe) ────────────────────────────────────────────

class Counter:
    def __init__(self):
        self._value = 0
        self._lock  = threading.Lock()

    def increment(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


# ── helpers ───────────────────────────────────────────────────────────────────

def get_company_token() -> str:
    token = os.environ.get("BRINGG_COMPANY_TOKEN", "").strip()
    if not token:
        print(
            "ERROR: set BRINGG_COMPANY_TOKEN env var to your stg2 company/admin token.",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def _http(req: urllib.request.Request):
    """Execute a urllib Request. Returns (status, body_dict)."""
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"error": "unparsable body"}
    except Exception as e:
        return None, {"error": str(e)}


def _retry_http(
    req_factory,
    *,
    rate_limiter: RateLimiter,
    max_retries: int = 4,
    conn_retries: int = 3,
):
    """
    Call req_factory() → urllib.Request, execute it, and retry on:
      - HTTP 429: sleep Retry-After header (or exponential 2^attempt seconds)
      - Connection error (status None): up to conn_retries times, 2 s backoff

    Returns (status, body_dict) of the final attempt.
    """
    rate_retries = 0
    net_retries  = 0

    while True:
        rate_limiter.acquire()
        req = req_factory()
        status, body = _http(req)

        if status == 429:
            if rate_retries >= max_retries:
                return status, body
            retry_after = None
            # urllib doesn't expose response headers on HTTPError after the fact,
            # so check if the body contains a hint; otherwise use exponential backoff.
            wait = float(body.get("retry_after") or body.get("Retry-After") or 0) or 2 ** (rate_retries + 1)
            print(
                f"  429 rate-limited — sleeping {wait:.1f}s (attempt {rate_retries + 1}/{max_retries})",
                file=sys.stderr,
            )
            time.sleep(wait)
            rate_retries += 1
            continue

        if status is None:
            if net_retries >= conn_retries:
                return status, body
            wait = 2.0
            print(
                f"  Connection error ({body.get('error')}) — retrying in {wait}s"
                f" (attempt {net_retries + 1}/{conn_retries})",
                file=sys.stderr,
            )
            time.sleep(wait)
            net_retries += 1
            continue

        return status, body


# ── task creation and assignment ──────────────────────────────────────────────

def _strip_comments(obj):
    """Recursively remove keys starting with '_' — used for template annotation keys."""
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_comments(v) for v in obj]
    return obj


def build_task_body(template: dict, driver_id: int, external_id: str) -> dict:
    body = _strip_comments(json.loads(json.dumps(template)))
    body["user_id"]     = driver_id
    body["team_ids"]    = [TEAM_ID]
    body["external_id"] = external_id
    return body


def create_task(
    template: dict,
    driver_id: int,
    external_id: str,
    token: str,
    rate_limiter: RateLimiter,
):
    """Create a single task. Returns task_id on success, None on failure."""

    def _make_req():
        body = build_task_body(template, driver_id, external_id)
        data = json.dumps(body).encode("utf-8")
        return urllib.request.Request(
            f"{BASE_URL}/tasks",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Token token={token}",
            },
        )

    status, resp = _retry_http(_make_req, rate_limiter=rate_limiter)
    if status in (200, 201):
        task_id = resp.get("task", {}).get("id") or resp.get("id")
        return task_id

    print(f"  WARN: create_task {external_id} → HTTP {status}: {resp}", file=sys.stderr)
    return None


def assign_task_to_run(
    task_id: int,
    run_external_id: str,
    token: str,
    rate_limiter: RateLimiter,
) -> bool:
    """
    PATCH a task to pin it to a run (prevents AD auto-merge).
    Returns True on success.
    """

    def _make_req():
        # TaskAssigner reads params[:run][:external_id] or params[:task][:run_external_id].
        # Nested task.run is ignored, so a 200 can be a no-op with run_id still null.
        data = json.dumps({
            "run": {"external_id": run_external_id},
            "task": {"run_external_id": run_external_id},
        }).encode("utf-8")
        return urllib.request.Request(
            f"{BASE_URL}/tasks/{task_id}",
            data=data,
            method="PATCH",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Token token={token}",
            },
        )

    status, resp = _retry_http(_make_req, rate_limiter=rate_limiter)
    if status in (200, 201):
        return True

    print(
        f"  WARN: assign task {task_id} → run {run_external_id} failed (HTTP {status}: {resp})",
        file=sys.stderr,
    )
    return False


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--drivers",         default="test-data/rate_drivers.csv",
                    help="CSV with columns: user_id,email (one row per driver)")
    ap.add_argument("--template",        default="rate_task_template.json",
                    help="Task JSON template (see rate_task_template.json)")
    ap.add_argument("--prefix",          required=True,
                    help="Unique external_id prefix for this batch, e.g. MA-STG2-RATE-K6E")
    ap.add_argument("--count",           type=int, default=70,
                    help="Number of drivers to use from the CSV (default: 70)")
    ap.add_argument("--runs-per-driver", type=int, default=1, dest="runs_per_driver",
                    help="Runs to create per driver (total runs = count × runs_per_driver)")
    ap.add_argument("--tasks-per-run",   type=int, default=1, dest="tasks_per_run",
                    help="Tasks per run (default: 1)")
    ap.add_argument("--output",          default="test-data/rate_run_task_mapping.csv",
                    help="Output CSV path")
    ap.add_argument("--canary",          action="store_true",
                    help="Create only 1 run and exit (verify before bulk)")
    args = ap.parse_args()

    token = get_company_token()

    with open(args.template) as f:
        template = json.load(f)

    if not template.get("task_type_id"):
        print("ERROR: task_type_id is not set in the template. Fill it in from an existing k6c task before seeding.", file=sys.stderr)
        sys.exit(1)

    drivers: list[int] = []
    with open(args.drivers, newline="") as f:
        for row in csv.DictReader(f):
            drivers.append(int(row["user_id"]))
            if len(drivers) >= args.count:
                break

    if not drivers:
        print("ERROR: no drivers found in CSV.", file=sys.stderr)
        sys.exit(1)

    total_runs = 1 if args.canary else len(drivers) * args.runs_per_driver

    print(
        f"Creating {total_runs} runs ({args.tasks_per_run} tasks each) with prefix {args.prefix}",
        file=sys.stderr,
    )
    print(f"Drivers: {len(drivers)} · Rate limit: {RATE_LIMIT_RPS} req/s · Workers: {MAX_WORKERS}",
          file=sys.stderr)

    # Estimate: creation pass uses (total_runs × tasks_per_run) requests, assign pass uses
    # (total_runs × tasks_per_run) more requests.
    total_requests = total_runs * args.tasks_per_run * 2
    est_min = total_requests / RATE_LIMIT_RPS / 60
    print(f"Estimated time: {est_min:.0f} min", file=sys.stderr)

    rate_limiter = RateLimiter(RATE_LIMIT_RPS, burst=MAX_WORKERS)
    progress     = Counter()

    # ── Phase 1: build the work list ──────────────────────────────────────────
    # Each item: (run_num, run_external_id, driver_id)
    work: list[tuple[int, str, int]] = []
    run_num = 0
    for _cycle in range(1 if args.canary else args.runs_per_driver):
        for driver_id in drivers:
            run_num += 1
            run_ext = f"{args.prefix}-{run_num:04d}"
            work.append((run_num, run_ext, driver_id))
            if args.canary:
                break
        if args.canary:
            break

    total_tasks = len(work) * args.tasks_per_run
    print(f"Total task creates: {total_tasks}", file=sys.stderr)

    # ── Phase 2: create all tasks concurrently ────────────────────────────────
    # result_map: run_external_id → (driver_id, [task_id, ...])
    result_map: dict[str, tuple[int, list[int]]] = {}
    result_lock = threading.Lock()

    def create_run_tasks(item: tuple[int, str, int]) -> str:
        """Worker: create all tasks for one run. Returns run_external_id."""
        run_num, run_ext, driver_id = item
        task_ids: list[int] = []
        ok = True

        for t_seq in range(1, args.tasks_per_run + 1):
            task_ext = f"{run_ext}-T{t_seq}"
            task_id  = create_task(template, driver_id, task_ext, token, rate_limiter)
            if task_id is None:
                print(
                    f"  ABORT: could not create {task_ext}, skipping run {run_ext}",
                    file=sys.stderr,
                )
                ok = False
                break
            task_ids.append(task_id)

            done = progress.increment()
            print(
                f"[{done}/{total_tasks}] {task_ext} → task {task_id}",
                file=sys.stderr,
                flush=True,
            )

        if ok and task_ids:
            with result_lock:
                result_map[run_ext] = (driver_id, task_ids)

        return run_ext

    print("\n── Phase 1: creating tasks ──────────────────────────────", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(create_run_tasks, item): item for item in work}
        for future in concurrent.futures.as_completed(futures):
            exc = future.exception()
            if exc:
                _, run_ext, _ = futures[future]
                print(f"  ERROR in run {run_ext}: {exc}", file=sys.stderr)

    created_runs = len(result_map)
    print(
        f"\n── Phase 1 done: {created_runs}/{len(work)} runs created successfully.",
        file=sys.stderr,
    )

    if not result_map:
        print("ERROR: no tasks were created. Exiting.", file=sys.stderr)
        sys.exit(1)

    # ── Phase 3: assign tasks to runs ─────────────────────────────────────────
    print("\n── Phase 2: assigning tasks to runs ─────────────────────", file=sys.stderr)
    assign_progress = Counter()
    assign_total    = sum(len(tids) for _, tids in result_map.values())

    def assign_run(run_ext: str) -> None:
        driver_id, task_ids = result_map[run_ext]
        for task_id in task_ids:
            ok = assign_task_to_run(task_id, run_ext, token, rate_limiter)
            done = assign_progress.increment()
            status_str = "ok" if ok else "FAIL"
            print(
                f"  assign [{done}/{assign_total}] task {task_id} → {run_ext} [{status_str}]",
                file=sys.stderr,
                flush=True,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(assign_run, run_ext): run_ext for run_ext in result_map}
        for future in concurrent.futures.as_completed(futures):
            exc = future.exception()
            if exc:
                run_ext = futures[future]
                print(f"  ERROR assigning run {run_ext}: {exc}", file=sys.stderr)

    print(f"\n── Phase 2 done.", file=sys.stderr)

    # ── Phase 4: write CSV ────────────────────────────────────────────────────
    # Preserve original insertion order (run_num order).
    ordered_run_exts = [run_ext for _, run_ext, _ in work if run_ext in result_map]

    rows = [
        {
            "run_id":          "",   # filled later via Redash
            "run_external_id": run_ext,
            "driver_id":       result_map[run_ext][0],
            "task_ids":        ",".join(str(t) for t in result_map[run_ext][1]),
        }
        for run_ext in ordered_run_exts
    ]

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run_id", "run_external_id", "driver_id", "task_ids"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nDone. {len(rows)} runs written to {args.output}", file=sys.stderr)

    if args.canary and rows:
        first = rows[0]
        print(
            f"\nCanary done. run_external_id={first['run_external_id']}, task_ids={first['task_ids']}",
            file=sys.stderr,
        )
        print("Verify in Redash/admin before continuing with the full batch.", file=sys.stderr)

    print(
        "Next: fill in run_id column via Redash, then run parse_runs_csv.py → accept_rate_tasks.py",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
