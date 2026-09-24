#!/usr/bin/env python3
"""
login_drivers.py — Bulk-login test drivers and collect authentication tokens.

Usage:
    python scripts/login_drivers.py \
        --drivers test-data/rate_drivers.csv \
        --start 1001 --end 1100 \
        --password "$BRINGG_DRIVER_PASSWORD" \
        --output test-data/driver_tokens.csv

Rate limit: ~6 req/min per IP. Script paces at 1 call per 10 s and retries
429/503/connection errors with exponential backoff (2, 4, 8, 16 s).
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

LOGIN_URL = "https://stg2-api.bringg.com/api/tokens"
PACE_SECONDS = 10          # 1 call per 10 s → 6/min
MAX_RETRIES = 4
BACKOFF_BASE = 2           # seconds: 2, 4, 8, 16


def parse_args():
    parser = argparse.ArgumentParser(
        description="Log in test drivers and collect authentication tokens."
    )
    parser.add_argument(
        "--drivers",
        default="test-data/rate_drivers.csv",
        help="Input CSV with columns user_id,email (default: test-data/rate_drivers.csv)",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="First user_id (inclusive) to process. Omit to start from the beginning.",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=None,
        help="Last user_id (inclusive) to process. Omit to process to the end.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Driver password. Falls back to env var BRINGG_DRIVER_PASSWORD.",
    )
    parser.add_argument(
        "--output",
        default="test-data/driver_tokens.csv",
        help="Output CSV path (default: test-data/driver_tokens.csv)",
    )
    return parser.parse_args()


def get_password(args):
    password = args.password or os.environ.get("BRINGG_DRIVER_PASSWORD")
    if not password:
        print(
            "ERROR: password is required. Pass --password or set BRINGG_DRIVER_PASSWORD.",
            file=sys.stderr,
        )
        sys.exit(1)
    return password


def read_drivers(path, start, end):
    """Read CSV and return rows filtered to [start, end] user_id range."""
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = int(row["user_id"])
                if start is not None and uid < start:
                    continue
                if end is not None and uid > end:
                    continue
                rows.append({"user_id": uid, "email": row["email"].strip()})
    except FileNotFoundError:
        print(f"ERROR: drivers file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"ERROR: missing expected column in CSV: {e}", file=sys.stderr)
        sys.exit(1)
    return rows


def do_login(email, password):
    """
    POST to /api/tokens.
    Returns (token, None) on success or (None, error_message) on failure.
    """
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        LOGIN_URL,
        data=payload,
        headers={"Content-Type": "application/json", "client": "iOS"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"URLError: {e.reason}"
    except OSError as e:
        return None, f"OSError: {e}"

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {e}"

    token = (data.get("user") or {}).get("authentication_token")
    if not token:
        return None, "missing authentication_token in response"

    return token, None


def login_with_retry(email, password):
    """
    Attempt login with up to MAX_RETRIES retries on transient errors.
    Returns (token, status) where status is 'ok' or 'failed'.

    Between retries, sleeps for exponential backoff.
    The per-call PACE sleep is done by the caller *after* a successful attempt.
    """
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            wait = BACKOFF_BASE ** attempt  # 2, 4, 8, 16
            print(
                f"  retry {attempt}/{MAX_RETRIES} in {wait}s (last error: {last_error})",
                file=sys.stderr,
            )
            time.sleep(wait)

        # Probe for a rate-limit response separately so we can treat it specially.
        payload = json.dumps({"email": email, "password": password}).encode("utf-8")
        req = urllib.request.Request(
            LOGIN_URL,
            data=payload,
            headers={"Content-Type": "application/json", "client": "iOS"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                status_code = resp.status
        except urllib.error.HTTPError as e:
            status_code = e.code
            body = b""
            if status_code in (429, 503):
                last_error = f"HTTP {status_code}"
                continue  # retry with backoff
            # Other HTTP errors are not retried
            last_error = f"HTTP {status_code}"
            break
        except (urllib.error.URLError, OSError) as e:
            last_error = f"connection error: {e}"
            continue  # retry with backoff

        # Parse response
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            last_error = "JSON decode error"
            continue

        token = (data.get("user") or {}).get("authentication_token")
        if not token:
            last_error = "missing authentication_token in response"
            continue  # retry — might be a transient server issue

        return token, "ok"

    return None, "failed"


def write_output_header(path):
    """Create (or overwrite) the output CSV and write the header row."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "email", "token", "status"])


def append_result(path, user_id, email, token, status):
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([user_id, email, token or "", status])


def main():
    args = parse_args()
    password = get_password(args)
    drivers = read_drivers(args.drivers, args.start, args.end)

    if not drivers:
        print("No drivers matched the given --start/--end range.", file=sys.stderr)
        sys.exit(0)

    print(
        f"Processing {len(drivers)} driver(s) "
        f"(user_id range: {drivers[0]['user_id']} – {drivers[-1]['user_id']})",
        file=sys.stderr,
    )
    print(f"Output: {args.output}", file=sys.stderr)
    print(f"Pace: 1 call per {PACE_SECONDS}s, up to {MAX_RETRIES} retries per driver.",
          file=sys.stderr)
    print("", file=sys.stderr)

    write_output_header(args.output)

    ok_count = 0
    failed_count = 0

    for i, driver in enumerate(drivers):
        uid = driver["user_id"]
        email = driver["email"]

        token, status = login_with_retry(email, password)

        append_result(args.output, uid, email, token, status)

        if status == "ok":
            ok_count += 1
            print(f"[{i+1}/{len(drivers)}] user_id={uid}  OK", file=sys.stderr)
        else:
            failed_count += 1
            print(f"[{i+1}/{len(drivers)}] user_id={uid}  FAILED", file=sys.stderr)

        # Pace: wait between calls (skip the wait after the last driver)
        if i < len(drivers) - 1:
            time.sleep(PACE_SECONDS)

    print("", file=sys.stderr)
    print(f"Done. {ok_count} ok, {failed_count} failed.", file=sys.stderr)
    print(f"Tokens written to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
