# BRNGG-55375 — QR Code PDF Compliance Load Tests

Load-testing suite for the Bringg QR-code PDF generation pipeline (Gotenberg + templates-service).  
Jira epic: **BRNGG-55375**  
Target environment: **stg2**

---

## Overview

The QR-code feature generates a PDF per driver run via Gotenberg (headless Chromium).  
This repo contains every artifact from scoping through active load-test execution:
- **Design & planning documents** — tech design, implementation plan, test cases, handoff notes
- **k6 load test scripts** — parallel (phase 3) and constant/ramping-arrival-rate (phase 5e)
- **Helper Python scripts** — task seeding, driver login, Grafana metric fetching, OpenSearch log queries, pipeline outcome CSV generation
- **Runbook** — step-by-step instructions for running, monitoring, and interpreting each scenario
- **Test reports** — filled-in MD reports for each completed scenario

---

## Repository layout

```
.
├── LOAD-TEST-RUNBOOK.md          # ← start here for running tests
├── BRNGG-55375-*.md              # design docs, implementation plan, test cases
├── BRNGG-57*.md                  # sub-story design docs (S2–S4)
├── scripts/
│   ├── load_test_50_parallel.js  # Phase 3 — 50-parallel /start burst
│   ├── load_test_rate.js         # Phase 5e — constant/ramping-arrival-rate
│   ├── seed_rate_tasks.py        # Create tasks in bulk for rate scenarios
│   ├── accept_rate_tasks.py      # Pre-accept tasks so drivers can start them
│   ├── accept_tasks.py           # Accept tasks (parallel scenario)
│   ├── accept_k6c_tasks.py       # Accept tasks (k6c variant)
│   ├── login_drivers.py          # Log in N drivers → writes smoke_tokens.csv
│   ├── fetch_grafana_metrics.py  # Pull Gotenberg metrics from Grafana and patch reports
│   ├── load_test_metrics.py      # Query OpenSearch for pipeline outcomes
│   ├── pull_pipeline_metrics.py  # Pull pipeline metrics via Redash
│   ├── parse_runs_csv.py         # Parse run outcome CSVs
│   ├── trigger_parallel_run_starts.py  # Fire /start requests in parallel
│   ├── rate_task_template.json   # Task body template for rate test seeding
│   ├── how-to-start-a-run.md     # Quick reference for /start API
│   └── test-data/                # ← GITIGNORED — contains live driver JWTs
└── print-receipt.pdf             # Sample PDF used during testing
```

---

## Test scenarios

| Phase | Scenario | Script | Status |
|---|---|---|---|
| 3 | 50-parallel `/start` burst | `load_test_50_parallel.js` | Completed (see `BRNGG-55375-load-test-results.md`) |
| 5e baseline | 1 req/s × 2 min | `load_test_rate.js --env baseline` | Completed ✓ |
| 5e find_capacity | ramp 10→30 req/s × 10 min | `load_test_rate.js --env find_capacity` | Completed ✓ |
| 5e soak | sustained 5 req/s × 60 min | `load_test_rate.js --env soak` | Not yet run |
| 5e spike | 0 → 50 req/s in 30 s | `load_test_rate.js --env spike` | Not yet run |

### Key findings (find_capacity — 2026-09-24)

- At 10→30 req/s the bottleneck shifts from our `pLimit` gate to **Gotenberg's Chromium capacity**
- 73.5 % of started runs got `webhook_delivered` (E2E p95 = 9.5 s, within 10 s SLA)
- 26.5 % got `render_returned_failure` (unavailable) with Gotenberg at 7.3 cores / 40 Chromium restarts
- Zero requests were shed — the pLimit gate was removed for the test

---

## Quick start

### Prerequisites

| Tool | Version |
|---|---|
| [k6](https://k6.io/docs/get-started/installation/) | ≥ 0.49 |
| Python | ≥ 3.9 |
| [Teleport](https://goteleport.com/docs/) | active session for `stg2` |

```bash
# Install k6
brew install k6
```

### 1 — Authenticate

```bash
# Teleport login (needed for OpenSearch and Grafana scripts)
tsh login --proxy=teleport.pme.gcloud.bringg.com

# Grafana: copy session cookies from DevTools → Application → Cookies
export GRAFANA_SESSION="<__Host-grv_app_session>"
export GRAFANA_SESSION_SUBJECT="<__Host-grv_app_session_subject>"
```

### 2 — Prepare driver tokens

> **Never commit `test-data/`** — it holds live driver JWTs for stg2.

```bash
# Log in 50 drivers (writes scripts/test-data/smoke_tokens.csv)
cd scripts
python3 login_drivers.py --merchant 60596 --count 50
```

### 3 — Seed tasks (rate scenarios)

```bash
python3 seed_rate_tasks.py --merchant 60596 --count 12000 --scenario find_capacity
python3 accept_rate_tasks.py --merchant 60596 --tokens test-data/smoke_tokens.csv
```

### 4 — Run the test

```bash
# Baseline (1 req/s)
k6 run -e SCENARIO=baseline scripts/load_test_rate.js

# Find-capacity (ramp 10→30 req/s over 10 min)
k6 run -e SCENARIO=find_capacity scripts/load_test_rate.js
```

⚠️ **Only fire phase 3 (parallel burst) or ramp scenarios with explicit go-ahead** — these hit staging hard.

### 5 — Fetch Gotenberg metrics

After each run, patch the report with Grafana numbers:

```bash
cd scripts
python3 fetch_grafana_metrics.py \
  --meta test-data/rate_baseline_2026-09-24-10-34_meta.json \
  --env stg2
```

### 6 — Pull pipeline outcomes (OpenSearch)

```bash
python3 load_test_metrics.py \
  --start "2026-09-24T10:32:00Z" \
  --end   "2026-09-24T10:35:00Z"
```

---

## Reports

Filled-in reports live in `scripts/test-data/` (gitignored — ask the author for copies).  
A summary for completed runs is in [`BRNGG-55375-load-test-results.md`](BRNGG-55375-load-test-results.md).

Confluence results page: https://bringg.atlassian.net/wiki/spaces/RD/pages/5393809409

---

## Author

Moslem Asaad — moslem.asaad@bringg.com
