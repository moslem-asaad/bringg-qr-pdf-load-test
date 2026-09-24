# Adeo stg2 test-task creation — reusable prompt

Copy/paste the prompt below and adjust the bracketed values. Read "Prerequisites" and
"Gotchas" first if you haven't run this before — they cover things that aren't obvious
from the prompt alone and will bite you otherwise.

---

## Prerequisites (one-time setup)

1. **The `bringg-test-data` plugin** (skill: `bringg-services-api`) from `claude-bringg-marketplace` must be available in your session.
2. **`redash-get` on PATH**, or reachable at `~/bringg/scripts/redash/redash-get` (ships with the `bringg-data-access` plugin at `scripts/redash/redash-get`).
3. **`REDASH_USER_KEY_STG2`** exported — your own STG2 Redash *user* API key (Redash UI → STG2 → Profile → API Key). Don't reuse someone else's.
4. **An active Teleport session** (`tsh login --proxy=teleport.pme.gcloud.bringg.com:443 ...`) — `redash-get` will prompt for this on first use if missing.
5. **The template itself**: either fetch [the Confluence page](https://bringg.atlassian.net/wiki/spaces/RD/pages/4993581057/EU-3+Adeo+handlebars+template) directly, or ask me for the local copy at `adeo_handlbars.md` (in this same folder) — it's the ground truth for which fields matter and won't be at that exact path on your machine.

## The prompt

> Use the `bringg-services-api` skill. Create **[N]** tasks on **stg2**, merchant **60596** ("Asher Test"), team **103769** ("Test team"), with the same conditions as before:
>
> **Template:** match every field read by the EU-3 Adeo handlebars template ([Confluence](https://bringg.atlassian.net/wiki/spaces/RD/pages/4993581057/EU-3+Adeo+handlebars+template)) — waypoints, per-waypoint customers, inventories, skills, addresses, driver notes, and `extras` (`services[]`, `shipper_nif`, `special_authorization_id`).
>
> **Task fields (on create):**
> - `task_type_id: 5` (pickup_and_delivery), 2 waypoints: pickup = Adeo warehouse (position 1), dropoff = randomized Jerusalem-area address (position 2)
> - Per-waypoint nested `customer` (pickup and dropoff must each get their own Customer record) **plus** a top-level `customer` (required — a 2-waypoint task without one fails with "No customer defined")
> - Inventory (2–4 items) on both waypoints: `pending: true` at pickup, `false` at dropoff, with weight/quantity/scan_string
> - `required_skills[]`, `total_handling_units{}`, `additional_attributes{}`, full pricing fields, `task_configuration_id`, `service_plan_id`, `tag_id`
> - `extras.services[]` (two Spanish service-line names), `extras.shipper_nif = "B84818442"`, `extras.special_authorization_id = "SA-<external_id>"`
> - Delivery window: today's date, 13:00–19:00 Asia/Jerusalem, `automatically_geocoded: false`, `verification_pin_code`, `etos`, confirmation flags, a driver note on each waypoint
>
> **Vehicle:** assign `vehicle_id = 1577` ("test rc", the truck) to every task via `update_task` (not settable on create). Trailer **1578** is already linked via `vehicles.truck_id = 1577` — don't try to recreate it (see Gotchas).
>
> **Driver & runs:** all tasks go to driver **62738** (Adi Amar). Create **[X]** runs, split as **[e.g. "4,3,3"]** — one run per group of tasks.
>
> **Canary first:** create 1 task, verify it on the replica (task row, waypoints, customers, inventory, task_notes, extras) before bulk-creating the rest. Use a fresh, incrementing `external_id` prefix (e.g. `MA-STG2-ADEO6-<date>`) so it doesn't collide with other people's data on this merchant.
>
> Give me the run IDs and one task per run when done.

## Gotchas (learned the hard way — read before running)

- **Merchant 60596 is a shared, heavily-reused test merchant.** It already has other people's teams/drivers/tasks/runs on it. Always use your own external_id prefix; never assume a clean slate; never bulk-touch anything not matching your own prefix.
- **This team's background auto-dispatch silently consolidates runs.** If you assign the same driver to multiple tasks one `update_task` call at a time using only `run: {is_planned: false}` (no external_id), AD will merge several of your intended runs into fewer than you asked for. **Fix:** always create runs via `update_task` with `run: {external_id: "your-unique-id"}` — the first call per external_id creates the run, subsequent calls with the *same* external_id deterministically attach more tasks to it, regardless of what AD is doing elsewhere.
- **No vehicle-write action is provisioned on this merchant's services API.** `create_vehicle`, `update_vehicle`, `create_vehicle_type`, `update_vehicle_type` — none of them have a key-pair. You cannot create or edit vehicles/trailers/vehicle types via the API here. Vehicles 1577 (truck) and 1578 (trailer, `truck_id=1577`) already exist and are wired up in the dashboard — reuse them, don't try to make new ones.
- **`runs.vehicle_id` can't be set via the API either** (`assign_run_vehicle` isn't provisioned). Only `task.vehicle_id` is settable (via `update_task`). If you want the vehicle to show at the *run* level (not just per-task), you have to assign it manually in the dashboard's "Assign a Vehicle for Route" dialog — and that dialog needs vehicle_type **capacity** fields (`max_total_weight`/`handling_units`) set, or it fails with "missing capacity."
- **`extras` is a full replace on `update_task`, not a merge.** If you ever patch `extras` after creation, fetch the task's current `extras` first and merge client-side, or you'll wipe out `services`/etc.
- **Rate limit:** ~9 req/s per merchant (2,800/5min), no `Retry-After` header — pace bulk calls and back off on 429.
- Prior batches on this merchant from this workstream (all cancelled): ADEO1–5, RUN1–5, plus an earlier plain 20-task batch.
