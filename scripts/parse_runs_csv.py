#!/usr/bin/env python3
"""
Convert the run-task mapping CSV exported from Claude task-creation into
the JSON format that accept_k6c_tasks.py and load_test_50_parallel.js expect.

The primary task is the FIRST task_id in each row (the one drivers accept).

Usage:
    python3 parse_runs_csv.py <input.csv> <output.json>

    python3 parse_runs_csv.py test-data/k6d_run_task_mapping.csv test-data/k6d_runs_parsed.json

Input CSV columns (order matters, header required):
    run_id, run_external_id, driver_id, task_ids

task_ids is a comma-separated list of ints (may be quoted): "9749740,9749741,9749742"
"""

import csv
import json
import sys


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.csv> <output.json>", file=sys.stderr)
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]

    rows = []
    with open(in_path, newline="") as f:
        for row in csv.DictReader(f):
            task_ids = [int(t.strip()) for t in row["task_ids"].split(",") if t.strip()]
            rows.append({
                "run_id": int(row["run_id"]),
                "run_external_id": row["run_external_id"],
                "driver_id": int(row["driver_id"]),
                "primary_task_id": task_ids[0],
                "all_task_ids": task_ids,
            })

    with open(out_path, "w") as f:
        json.dump(rows, f, indent=2)

    print(f"Wrote {len(rows)} runs to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
