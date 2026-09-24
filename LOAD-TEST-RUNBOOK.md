# Load Test Runbook — 50-Parallel PDF Render Burst

**Environment:** stg2 · merchant 60596  
**Drivers:** 68514–68563 (50 pre-seeded test drivers, `ma.drv1k.NNNN@seed.bringg.test`, password: `123456`)  
**Tool versions required:** Python 3.9+, [k6](https://k6.io/docs/get-started/installation/) v0.49+

---

## Overview

The test fires 50 `/start` requests simultaneously to stress the PDF render pipeline (templates-service → Gotenberg). It has three distinct phases:

| Phase | What happens | Who triggers it |
|---|---|---|
| **1. Seed** | Create 50 runs with 1 task each, assigned to the 50 test drivers | Setup script / admin |
| **2. Accept** | Each driver accepts their primary task | `accept_tasks.py` |
| **3. Burst** | All 50 `/start` calls fire at the same instant | k6 — **needs explicit go-ahead every time** |

Phases 1 and 2 can run at any pace. **Only Phase 3 is the load event** — treat it as a controlled action requiring deliberate confirmation.

---

## Phase 0 — Smoke test: validate the full pipeline with 1 driver + 1 task

Run this before any scaled batch. It exercises every script end-to-end and confirms the PDF render pipeline fires correctly. Takes about 15 minutes.

### 0a. Create the drivers CSV for 1 driver

Driver emails follow the pattern `ma.drv1k.NNNN@seed.bringg.test` (e.g. `0001`, `0002`, …). All share password `123456`.

```bash
echo "user_id,email" > scripts/test-data/rate_drivers.csv
echo "68514,ma.drv1k.0001@seed.bringg.test" >> scripts/test-data/rate_drivers.csv
```

### 0b. Log in the driver

```bash
cd scripts
BRINGG_DRIVER_PASSWORD=123456 python3 login_drivers.py \
  --drivers test-data/rate_drivers.csv \
  --start 68514 --end 68514 \
  --output test-data/smoke_tokens.csv
```

Expected output: `[1/1] user_id=68514  OK`

### 0c. Fill in the task template

Open `scripts/rate_task_template.json` and set `task_type_id` to the value from an existing k6c task (check Redash). The field is `null` by default — the seed script will abort if it's not set.

### 0d. Seed 1 run + 1 task (canary)

```bash
BRINGG_COMPANY_TOKEN=<admin_token> python3 seed_rate_tasks.py \
  --drivers  test-data/rate_drivers.csv \
  --template rate_task_template.json \
  --prefix   MA-STG2-SMOKE \
  --count    1 \
  --canary \
  --output   test-data/smoke_mapping.csv
```

Expected: prints `[1/1] MA-STG2-SMOKE-0001-T1 → task <ID>` then exits. Verify the task row exists in Redash.

### 0e. Fill in run_id and convert

Look up the run_id for `MA-STG2-SMOKE-0001` in Redash:
```sql
SELECT id, external_id FROM runs WHERE external_id = 'MA-STG2-SMOKE-0001';
```

Edit `test-data/smoke_mapping.csv` to fill in the `run_id` column, then:
```bash
python3 parse_runs_csv.py test-data/smoke_mapping.csv test-data/smoke_runs.json
```

### 0f. Accept the task

```bash
python3 accept_rate_tasks.py \
  --runs   test-data/smoke_runs.json \
  --tokens test-data/smoke_tokens.csv \
  --output test-data/smoke_tasks.json
```

Expected: `1 runs, 1 driver tokens available … accepted=True … Done. 1 tasks accepted across 1 drivers.`

### 0g. Fire 1 iteration with k6

```bash
K6_WEB_DASHBOARD=true \
k6 run \
  -e TASKS_FILE=test-data/smoke_tasks.json \
  -e ADMIN_TOKEN=<admin_token> \
  -e SCENARIO=baseline \
  load_test_rate.js
```

k6 will fire 1 req/s for 2 min (120 iterations total). **Only the first iteration will succeed** — the task is started and the run closed; subsequent iterations detect the pool is exhausted and skip gracefully with a warning. That is correct and expected.

### 0h. Verify the PDF rendered

Check Grafana Gotenberg dashboard for 1 render spike, and OpenSearch for a `webhook_delivered` event on run `MA-STG2-SMOKE-0001`. If both appear, the full pipeline is confirmed.

---

## Prerequisites

### 1. Install k6
```bash
brew install k6          # macOS
# or: https://k6.io/docs/get-started/installation/
```

### 2. Unzip the shared folder and enter the scripts directory

You will receive a zip or shared Drive folder containing the `scripts/` directory and this runbook. Extract it and navigate into the scripts directory:

```bash
unzip BRNGG-55375-load-test.zip   # or however it was shared
cd scripts
```

All commands in this runbook assume you are inside the `scripts/` directory unless noted otherwise.

### 3. Teleport access to stg2
You need an active Teleport session to reach `stg2-api.bringg.com`. Confirm with:
```bash
curl -s https://stg2-api.bringg.com/ping
```
Expected response: `{"success":true}` or similar. If you get a connection error, re-authenticate via Teleport first.

---

## Phase 1 — Seed: create runs and assign tasks

> Skip this phase if tasks are already created and assigned (e.g. re-using a previous batch's pre-planned runs).

Task creation is done via Claude using the **`bringg-services-api`** skill (from `claude-bringg-marketplace`). You do NOT run a script — you paste a prompt into Claude.

### 1a. Prerequisites

- The `bringg-services-api` skill must be available in your Claude session (`claude-bringg-marketplace` repo, follow its install instructions).
- An active Teleport session to stg2.
- A unique external_id prefix for this batch (e.g. `MA-STG2-RUNK6D` for the next batch after `K6C`). **Never reuse a prefix** — IDs must be unique per batch so results don't mix.

### 1b. Driver pool

50 pre-seeded test drivers, one per run:

| user_id range | Email pattern | Count |
|---|---|---|
| 68514 – 68563 | `ma.drv1k.0001@seed.bringg.test` … `ma.drv1k.0050@seed.bringg.test` | 50 |

> Verify `user_id` values via Redash before using them — do not compute by hand.

### 1c. Task structure per run

Each run has **1 task**. That task is the one the driver accepts and starts — it must trigger a PDF render (templates-service → Gotenberg) when the run starts. Use the same task shape as previous batches:

- `task_type_id`: match the existing batch tasks (check the previous batch's tasks via Redash or Bringg admin if unsure)
- `user_id`: the driver assigned to this run
- `team_ids: [103769]`
- `ready_to_execute: true`
- A top-level `customer` object (required — a task without one is rejected)
- At least one `way_point` (position 2 dropoff)
- `external_id`: `<PREFIX>-<NNN>-T1` (e.g. `MA-STG2-RUNK6D-001-T1`)

### 1d. Prompt for Claude

Paste this prompt into a Claude session that has the `bringg-services-api` skill:

```
Use the bringg-services-api skill. Create 50 runs on stg2, merchant 60596 ("Asher Test"),
team 103769 ("Test team"). Each run has 1 task. One driver per run, using this pool:
user_id 68514–68563 (ma.drv1k.0001–0050@seed.bringg.test, password 123456). Verify user_ids via Redash.

Task shape: match the tasks from the previous k6 batch (run external_ids like
MA-STG2-RUNK6C-*) — same task_type_id, customer, waypoints, and any fields needed to
trigger a PDF render when the run starts.

Naming: use prefix MA-STG2-RUNK6D for this batch (or the next unused prefix).
Run external_ids: MA-STG2-RUNK6D-001 … MA-STG2-RUNK6D-050.
Task external_ids: MA-STG2-RUNK6D-001-T1 … MA-STG2-RUNK6D-050-T1 (one task per run).

IMPORTANT: assign each task to its run using update_task with run: {external_id: "MA-STG2-RUNK6D-NNN"}.
Do NOT use run: {is_planned: false} alone — auto-dispatch on this team will merge runs silently.
The external_id on the run create is the only safe way to control grouping.

Canary first: create run 001 (1 task), verify the task row and run grouping, then
bulk-create the remaining 49 runs.

When done, give me the full mapping as a CSV table:
run_id, run_external_id, driver_id, task_ids
```

### 1e. Export and convert the mapping

Once Claude finishes, copy the CSV table it outputs and save it to:
```
scripts/test-data/k6d_run_task_mapping.csv
```

Make sure the header row is present:
```
run_id,run_external_id,driver_id,task_ids
65382,MA-STG2-RUNK6D-001,68514,9750001
…
```

Then convert to JSON for the accept script:
```bash
cd scripts
python3 parse_runs_csv.py test-data/k6d_run_task_mapping.csv test-data/k6d_runs_parsed.json
```

> The task_id in each row becomes the `primary_task_id` that gets accepted in Phase 2.

### Gotchas (learned from prior batches)

- **AD auto-consolidation**: if you call `update_task` with only `run: {is_planned: false}`, the background auto-dispatch silently merges multiple tasks into fewer runs. Always include `run: {external_id: "..."}` on every `update_task` call to force run separation.
- **Rate limit**: ~9 req/s per merchant on the services API. Claude's skill paces this automatically; if you hit 429s, back off.
- **Merchant 60596 is shared**: always use your own external_id prefix; never touch runs not matching your prefix.

---

## Phase 2 — Accept: prepare each driver's primary task

Each driver must accept their primary task before `/start` will work. The accept script does this automatically using the driver tokens.

### 2a. Get driver tokens (first time, or if tokens expired)

```bash
# All 50 burst-test drivers at once (single machine, ~8 min):
python3 login_drivers.py \
  --drivers test-data/burst_drivers.csv \
  --password 123456 \
  --output   test-data/k6_driver_tokens.csv
```

For large pools (rate tests) you can split the range across machines — each machine gets its own IP budget (~6 req/min):

```bash
# Machine 1:
python3 login_drivers.py --start 68514 --end 68553 \
  --drivers test-data/rate_drivers.csv \
  --password 123456 \
  --output test-data/tokens_slice_1.csv

# Machine 2 (simultaneously):
python3 login_drivers.py --start 68554 --end 68593 \
  --drivers test-data/rate_drivers.csv \
  --password 123456 \
  --output test-data/tokens_slice_2.csv
```

The script paces at 1 req/10 s and retries up to 4× with exponential backoff on 429s. Tokens are valid for ~24 h; re-run only when they expire.

**Never commit token files to git.** `test-data/` is in `.gitignore` for this reason.

### 2b. Run the accept script

Pass the runs JSON and one or more token CSV files on the command line — no hardcoded paths:

```bash
cd scripts
python3 accept_rate_tasks.py \
  --runs   test-data/k6d_runs_parsed.json \
  --tokens test-data/k6_driver_tokens.csv test-data/tokens_slice_2.csv \
  --output test-data/k6d_runs_with_tokens.json
```

It reads the parsed runs JSON + all token CSVs, calls `POST /api/tasks/:id/accept` for each primary task, and writes the with-tokens JSON — the direct input to k6.

Expected output:
```
50 runs, 50 driver tokens available
[1/50] run=65382 (MA-STG2-RUNK6C-001) driver=68514 task=9749740 http=200 accepted=True
…
Done. 50/50 runs accepted and ready.
```

If any tasks come back as something other than `accepted=True`, check:
- Is the driver already in an open run? (Close it via `POST /runs/bulk_close`)
- Did the task expire or get cancelled?

---

## Phase 3 — Burst: fire the load test

> ⚠️ **This step fires real traffic at stg2. Confirm explicitly before running.**

```bash
cd scripts
k6 run -e RUNS_FILE=test-data/k6c_runs_with_tokens.json load_test_50_parallel.js
```

k6 will:
1. Spin up 50 VUs simultaneously
2. Each VU calls `POST /api/tasks/:id/start` for its assigned run
3. Write results to `test-data/k6_summary.json` and `test-data/k6_report.html`

### What to watch for

- All 50 HTTP responses should be `200 OK` with `success: true`
- `run_id` in each response should match the pre-planned run id
- The k6 terminal output shows latency and counter values in real time

---

## Phase 4 — Read the results

### k6 report
```bash
open test-data/k6_report.html
```
Shows: requests, latency (p50/p90/p95/max), `run_started_new_run` counter, and unexpected-state or failure counts.

### Pipeline outcomes (OpenSearch)
Query `logstash-*` for `run:started` events matching the run external IDs (`MA-STG2-RUNK6C-*`). Look for:
- `webhook_delivered` — PDF rendered and delivered
- `render_returned_failure` — PDF was shed or failed

### Gotenberg dashboard (Grafana)
```
https://grafana-pme.teleport.pme.gcloud.bringg.com/d/gotenberg-overview/gotenberg
```
Set `Environment = stg2`, time range = burst window ± 5 min. Key panels:
- **Chromium queue — requests waiting** (peak depth shows how many queued internally)
- **CPU cores per pod** (expected ~0.2 cores; spikes indicate overload)
- **Memory working set** (normal ~1 GiB; limit 2 GiB)
- **Chromium restarts** (should be 0)

---

## Cleanup

### Close open runs (after the test)
```bash
# Get open run ids for merchant 60596
# Then close via admin/dashboard token:
curl -X POST https://stg2-api.bringg.com/runs/bulk_close \
  -H "authorization: Token token=<admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"run_ids": [65382, 65383, ...]}'
```

### Cancel unused tasks
Via the services API action `kmae04kd`:
```
POST {BASE}/services/kmae04kd/{key1}/{key2}/
{"id": <task_id>}
```

---

---

## Phase 5 — Rate-based scenarios (no pLimit gate)

These scenarios require the pLimit gate to be **removed on stg2** (branch `BRNGG-55375-remove-plimit-gate` on templates-service, already deployed to stg2 for Batch 3). See PR #391.

### Scenario overview

Each run has **1 task** (1 task = 1 start = 1 PDF render). Tasks and runs are interchangeable below.

| Scenario | Rate | Duration | Runs/tasks needed | Drivers needed |
|---|---|---|---|---|
| `baseline` | 1 req/s | 2 min | ~120 | 5 |
| `find_capacity` | ramp 10→30/s | 10 min | ~12 000 | 80 |
| `soak` | 30/s steady | 25 min | ~45 000 | 80 |
| `spike` | 30→150/s×1min→30/s×2min | 3 min total | ~13 000 | 380 at peak |

Each VU cycle is ~2.5 s (start + close + 0.5 s sleep), so each driver sustains ~0.4 req/s.

> **Driver count**: the existing 50 drivers (68514–68563) are sufficient for `baseline` only. For `soak` and `find_capacity` provision 80 drivers; for `spike` at 150 req/s provision 380. Provision additional drivers first, add them to `test-data/rate_drivers.csv`, and re-run `login_drivers.py` for the new ones.

### 5a. Provision driver tokens

Ensure you have tokens for all drivers in your pool. Tokens for the original 50 drivers are in `test-data/k6b_driver_tokens.csv`. For new drivers:

```bash
cd scripts
python3 login_drivers.py --output test-data/rate_driver_tokens.csv
```

### 5b. Seed tasks

Two options — choose one:

**Option A — Via Claude skill**

Paste this prompt into a Claude session with the `bringg-services-api` skill. Adjust `PREFIX`, driver count, and run count for your scenario (see table above). At ~9 req/s the skill creates roughly 9 runs/minute; 45 000 runs takes ~83 minutes — start it overnight.

```
Use the bringg-services-api skill. Create <N> runs on stg2, merchant 60596 ("Asher Test"),
team 103769 ("Test team"). Each run has 1 task. Use this driver pool (round-robin):
user_id <first>–<last> (<N> drivers total). Verify user_ids via Redash before starting.

Task shape: match the tasks from the previous k6 batch (run external_ids like
MA-STG2-RUNK6C-*) — same task_type_id, customer, waypoints, and any fields needed to
trigger a PDF render when the run starts.

Naming: use prefix <PREFIX> (e.g. MA-STG2-SOAK-K6E). Never reuse a prefix.
Run external_ids: <PREFIX>-0001 … <PREFIX>-<NNNN>.
Task external_ids: <PREFIX>-0001-T1 … <PREFIX>-<NNNN>-T1 (one task per run).

IMPORTANT: assign each task to its run using update_task with run: {external_id: "<PREFIX>-NNNN"}.
Do NOT use run: {is_planned: false} alone — auto-dispatch on this team will merge runs silently.

Canary first: create run 0001 (1 task), verify the task row and run grouping, then
bulk-create the rest in batches of 50.

When done, give me the full mapping as a CSV table:
run_id, run_external_id, driver_id, task_ids
```

Scenario-specific values:

| Scenario | N (runs) | Driver pool | PREFIX example |
|---|---|---|---|
| `baseline` | 120 | 68514–68518 (5 drivers) | MA-STG2-BASE-K6E |
| `find_capacity` | 12 000 | 68514–68593 (80 drivers) | MA-STG2-RAMP-K6E |
| `soak` | 45 000 | 68514–68593 (80 drivers) | MA-STG2-SOAK-K6E |
| `spike` | 13 000 | 68514–68893 (380 drivers) | MA-STG2-SPIK-K6E |

Save the CSV Claude outputs to `test-data/<prefix>_run_task_mapping.csv`.

**Option B — Via `seed_rate_tasks.py`** (automated, requires admin API access):

The script creates tasks in parallel (8 concurrent workers) with retry on 429s, then assigns tasks to runs. For large batches (soak = 45 000 tasks) you can run multiple instances simultaneously with non-overlapping prefixes — they share the ~9 req/s merchant budget, but automatic backoff prevents conflicts.

```bash
# First, fill in rate_task_template.json (task_type_id, customer, waypoints)
# from an existing k6c task — check Redash or bringg admin.

# Soak — 45 000 tasks, 80 drivers × 563 runs each.
# Split into 3 parallel batches (different prefixes → no overlap):
BRINGG_COMPANY_TOKEN=<admin_token> python3 seed_rate_tasks.py \
  --drivers  test-data/rate_drivers.csv \
  --template rate_task_template.json \
  --prefix   MA-STG2-SOAK-K6E-A \
  --count    80 --runs-per-driver 188 \
  --output   test-data/soak_k6e_A_mapping.csv &

BRINGG_COMPANY_TOKEN=<admin_token> python3 seed_rate_tasks.py \
  --prefix MA-STG2-SOAK-K6E-B \
  --count  80 --runs-per-driver 188 \
  --output test-data/soak_k6e_B_mapping.csv &

BRINGG_COMPANY_TOKEN=<admin_token> python3 seed_rate_tasks.py \
  --prefix MA-STG2-SOAK-K6E-C \
  --count  80 --runs-per-driver 187 \
  --output test-data/soak_k6e_C_mapping.csv &

wait   # all three finish before proceeding
cat test-data/soak_k6e_A_mapping.csv \
    <(tail -n +2 test-data/soak_k6e_B_mapping.csv) \
    <(tail -n +2 test-data/soak_k6e_C_mapping.csv) \
    > test-data/soak_k6e_run_task_mapping.csv
```

Canary first (always):
```bash
BRINGG_COMPANY_TOKEN=<admin_token> python3 seed_rate_tasks.py \
  --prefix MA-STG2-SOAK-K6E-A --count 1 --canary \
  --output test-data/soak_canary.csv
```

After seeding, fill in the `run_id` column via Redash:
```sql
SELECT id, external_id FROM runs
WHERE external_id LIKE 'MA-STG2-SOAK-K6E-%' ORDER BY id;
```

Then convert to JSON:
```bash
python3 parse_runs_csv.py test-data/soak_k6e_run_task_mapping.csv test-data/soak_k6e_runs_parsed.json
```

### 5c. Accept tasks and build the interleaved task file

Run once per scenario using that scenario's parsed JSON and all relevant token files. Pass all token CSV slices together — the script merges them automatically:

```bash
cd scripts
python3 accept_rate_tasks.py \
  --runs   test-data/soak_k6e_runs_parsed.json \
  --tokens test-data/k6_driver_tokens.csv \
           test-data/tokens_slice_2.csv \
           test-data/tokens_slice_3.csv \
  --output test-data/soak_k6e_tasks.json
```

The script accepts each driver's tasks and writes them in **round-robin order by driver**, so consecutive k6 iteration IDs never collide on the same driver.

Expected output:
```
45000 runs, 80 driver tokens available
[1/45000] MA-STG2-SOAK-K6E-0001 driver=68514 task=9800001 http=200 accepted=True
…
Done. 45000 tasks accepted across 80 drivers.
Tasks available:    45000
soak  (30/s × 25min):  need 45 000 — OK
spike (150/s × 1min):  need  9 000 — OK
```
> If the capacity check says INSUFFICIENT, seed more runs and re-run accept, appending with a different batch prefix.

### 5d. Prepare per-scenario task files

Each scenario needs its own pre-accepted task file — a distinct slice of runs so scenarios don't share tasks (a started+closed task cannot be reused).

```bash
cd scripts

# Baseline — 120 tasks, any 5 drivers
python3 accept_rate_tasks.py \
  --runs   test-data/base_k6e_runs_parsed.json \
  --tokens test-data/k6_driver_tokens.csv \
  --output test-data/base_k6e_tasks.json

# Find capacity — 12 000 tasks, 80 drivers
python3 accept_rate_tasks.py \
  --runs   test-data/ramp_k6e_runs_parsed.json \
  --tokens test-data/k6_driver_tokens.csv test-data/tokens_slice_2.csv \
  --output test-data/ramp_k6e_tasks.json

# Soak — 45 000 tasks, 80 drivers
python3 accept_rate_tasks.py \
  --runs   test-data/soak_k6e_runs_parsed.json \
  --tokens test-data/k6_driver_tokens.csv test-data/tokens_slice_2.csv \
  --output test-data/soak_k6e_tasks.json

# Spike — 13 000 tasks, 380 drivers
python3 accept_rate_tasks.py \
  --runs   test-data/spik_k6e_runs_parsed.json \
  --tokens test-data/k6_driver_tokens.csv test-data/tokens_slice_2.csv test-data/tokens_slice_3.csv \
  --output test-data/spik_k6e_tasks.json
```

### 5e. Run scenarios in sequence

> ⚠️ **Confirm explicitly before firing each scenario. Each fires real traffic at stg2.**
>
> Run in order: **baseline → find_capacity → soak → spike**. Each builds on the reference point the previous one establishes.

```bash
cd scripts

# 1. Baseline — 1 req/s × 2 min. Establishes the no-load render latency reference.
K6_WEB_DASHBOARD=true \
K6_WEB_DASHBOARD_EXPORT=test-data/base_k6e_live.html \
k6 run \
  -e TASKS_FILE=test-data/base_k6e_tasks.json \
  -e ADMIN_TOKEN=<admin_token> \
  -e SCENARIO=baseline \
  load_test_rate.js

# 2. Find capacity — ramp 10→30/s × 10 min. Watch where p95 jumps.
K6_WEB_DASHBOARD=true \
K6_WEB_DASHBOARD_EXPORT=test-data/ramp_k6e_live.html \
k6 run \
  -e TASKS_FILE=test-data/ramp_k6e_tasks.json \
  -e ADMIN_TOKEN=<admin_token> \
  -e SCENARIO=find_capacity \
  load_test_rate.js

# 3. Soak — 30/s × 25 min. Watch for memory growth and p95 drift.
K6_WEB_DASHBOARD=true \
K6_WEB_DASHBOARD_EXPORT=test-data/soak_k6e_live.html \
k6 run \
  -e TASKS_FILE=test-data/soak_k6e_tasks.json \
  -e ADMIN_TOKEN=<admin_token> \
  -e SCENARIO=soak \
  load_test_rate.js

# 4. Spike — 30→150/s×1min→30/s recovery × 2 min. Watch recovery time.
K6_WEB_DASHBOARD=true \
K6_WEB_DASHBOARD_EXPORT=test-data/spik_k6e_live.html \
k6 run \
  -e TASKS_FILE=test-data/spik_k6e_tasks.json \
  -e ADMIN_TOKEN=<admin_token> \
  -e SCENARIO=spike \
  load_test_rate.js
```

`K6_WEB_DASHBOARD=true` opens a live browser dashboard on `http://localhost:5665` while the test runs. The `K6_WEB_DASHBOARD_EXPORT` path saves the live dashboard as HTML at test end; the `handleSummary` report (`test-data/rate_<scenario>_*_report.html`) is written separately with counters and latency tables.

### 5e. Read the results

After the test finishes, open the HTML report:
```bash
open test-data/rate_soak_*_report.html
```

Key things to observe per scenario:

**baseline** — note the baseline p95 render latency with no competing load. This is your reference point.

**find_capacity** — watch where p95 latency jumps (marks Gotenberg saturation) or where `run_start_failed` starts climbing. The inflection point is your system's safe ceiling.

**soak** — p95 should remain stable across the full 25 min. Memory creep in Gotenberg (Grafana: memory working set panel) or rising p95 indicate gradual degradation.

**spike** — p95 during the 150/s spike shows shed/queue depth; the recovery phase (30/s tail) shows how quickly latency returns to baseline.

**Gotenberg dashboard:**
```
https://grafana-pme.teleport.pme.gcloud.bringg.com/d/gotenberg-overview/gotenberg?var-environment=stg2
```
Set time range to the test window ± 5 min. Key panels:
- **CPU cores per pod** — expected ≤0.2 cores at 30/s (vs ~0.2 peak in Batch 3 burst)
- **Memory working set** — watch for growth during soak; limit is 2 GiB
- **Chromium queue — requests waiting** — depth shows how Gotenberg queues under the spike
- **Chromium restarts** — should be 0

### 5f. Fetch Gotenberg metrics and patch reports

Run this **after each scenario** while your Teleport session is still active. It queries Grafana for the exact test time window and patches the CPU, memory, queue depth, and restart numbers into both `_report.md` and `_report.html`.

**One-time setup — get your Teleport session cookies:**
1. Open the Grafana URL in your browser (logged in via Teleport)
2. DevTools → Application → Cookies → copy both values:
   - `__Host-grv_app_session`
   - `__Host-grv_app_session_subject`

```bash
export GRAFANA_SESSION="<__Host-grv_app_session value>"
export GRAFANA_SESSION_SUBJECT="<__Host-grv_app_session_subject value>"
```

**Run after each scenario** (replace `<suffix>` with the timestamp in the filename):

```bash
cd scripts

# after baseline
python3 fetch_grafana_metrics.py --meta test-data/rate_baseline_<suffix>_meta.json --env stg2

# after find_capacity
python3 fetch_grafana_metrics.py --meta test-data/rate_find_capacity_<suffix>_meta.json --env stg2

# after soak
python3 fetch_grafana_metrics.py --meta test-data/rate_soak_<suffix>_meta.json --env stg2

# after spike
python3 fetch_grafana_metrics.py --meta test-data/rate_spike_<suffix>_meta.json --env stg2
```

The script prints what it fetched to stderr and patches the reports in-place. Open the updated HTML report to verify:
```bash
open test-data/rate_<scenario>_<suffix>_report.html
```

> **Note:** Teleport session cookies expire at the end of your browser session. Re-copy them if you get HTTP 401/403 errors.

---

## File reference

Replace `k6d` with the actual batch prefix you chose in Phase 1.

| File | Purpose |
|---|---|
| `test-data/k6d_run_task_mapping.csv` | Raw CSV exported from Claude after task creation |
| `test-data/k6d_runs_parsed.json` | Run/task/driver mapping (no tokens) — output of `parse_runs_csv.py` |
| `test-data/k6b_driver_tokens.csv` | Driver login tokens — **gitignored, never commit** |
| `test-data/k6d_runs_with_tokens.json` | Combined input for k6 (tokens + run data) |
| `test-data/k6_summary.json` | Raw k6 metrics after a run |
| `test-data/k6_report.html` | Human-readable k6 report |
| `parse_runs_csv.py` | Converts run-task CSV → JSON for the accept scripts |
| `load_test_50_parallel.js` | k6 script — the 50-parallel burst (Phases 1–4) |
| `load_test_rate.js` | k6 script — rate-based scenarios: baseline / find_capacity / soak / spike |
| `accept_k6c_tasks.py` | Accepts primary tasks for the burst test (k6c/k6d batches) |
| `seed_rate_tasks.py` | Bulk-creates runs+tasks for rate tests via admin API |
| `accept_rate_tasks.py` | Accepts tasks for rate tests and writes interleaved driver JSON |
| `rate_task_template.json` | Task payload template for seed_rate_tasks.py (fill in before use) |
| `test-data/rate_drivers.csv` | Driver pool for rate tests (user_id,email — gitignored) |
| `test-data/rate_*_tasks.json` | Interleaved accepted-task file for load_test_rate.js — **gitignored** |

---

## Safety rules

1. **Never commit anything in `test-data/`** — tokens live there.
2. **Always confirm before Phase 3** — the burst fires real traffic.
3. **One burst per batch of runs** — re-running `/start` on an already-started run folds the task into the existing run, not a new one.
4. **Driver tokens expire in ~24 h** — re-run `login_drivers.py` if you see `authentication_token: null`.
5. **Each driver must have no open run** before Phase 3 — otherwise the task attaches to the old run and no `run:started` fires.
