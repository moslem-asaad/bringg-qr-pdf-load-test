# How to start a run on stg2 (merchant 60596)

A "run" doesn't exist as its own object until a task under it gets started —
`run_id` is `null` on a freshly created task, and `NextRunProvider` only
creates the `Run` row at start time (`hagmonia/app/services/runs/
next_run_provider.rb`). This is the full, verified procedure to go from
nothing to a genuinely fresh `run:started` event.

## The three-step lifecycle (all required, in order)

### 1. Create the task, assigned to a driver

Via the tokenized services API (`bringg-services-api` skill), action
`create_task` (`6f15901b`):

```
POST {BASE}/services/6f15901b/{key1}/{key2}/
Content-Type: application/json

{
  "external_id": "<unique>",
  "title": "...",
  "user_id": <driver_user_id>,
  "ready_to_execute": true,
  "team_ids": [103769],
  "customer": { "name": "...", "address": "...", "lat": ..., "lng": ..., "city": "Jerusalem", "country_code": "il" },
  "way_points": [{
    "position": 2,
    "pickup_dropoff_option": 1,
    "lat": ..., "lng": ..., "address": "...", "city": "Jerusalem",
    "no_earlier_than": "<ISO8601>", "no_later_than": "<ISO8601>",
    "automatically_geocoded": false
  }]
}
```

Result: task lands at **`status: 1` ("assigned")**, `run_id: null`. This is
true even though `user_id` was set at creation — it does **not** land at
`status: 6` ("accepted") automatically, despite what earlier ad-hoc testing
this epic seemed to assume. Don't skip step 2.

### 2. Accept the task (as the driver)

```
POST https://stg2-api.bringg.com/api/tasks/{task_id}/accept
authorization: Token token=<driver_token>
client: iOS
```

Requires the **driver's own token** (login below). Moves the task to
**`status: 6` ("accepted")**. Skipping this step makes step 3 fail with
`"You can't start task that is not accepted"`
(`hagmonia/app/controllers/api/v2/tasks_controller.rb:1040-1044`).

### 3. Start the task (as the driver)

```
POST https://stg2-api.bringg.com/api/tasks/{task_id}/start
authorization: Token token=<driver_token>
client: iOS
```

This is the step that actually creates the `Run` row and fires `run:started`.
Response includes `task.run_id` — the new run's id.

**Important — the driver must not already have another open run**, or the
new task gets folded into that existing run instead of creating a fresh one
(no new `run:started` fires). Check first:

```sql
SELECT id, started_at, ended_at FROM runs WHERE user_id = <driver_id> AND merchant_id = 60596 AND ended_at IS NULL;
```

If one exists, close it first (admin/dashboard token, not driver token):

```
POST https://stg2-api.bringg.com/runs/bulk_close
authorization: Token token=<admin_dashboard_token>
Content-Type: application/json

{"run_ids": [<old_run_id>, ...]}
```

## Getting a driver token

Seeded test drivers: `ma.drv1k.NNNN@seed.bringg.test`, password `123456`,
`user_id = 68454 + NNNN` (verify via Redash, don't compute by hand — an
off-by-one here is easy to make).

```
POST https://stg2-api.bringg.com/api/tokens
Content-Type: application/json
client: iOS

{"email": "ma.drv1k.NNNN@seed.bringg.test", "password": "123456", "User-Agent": "Bringg/1.131.0 (iOS)"}
```

`client: iOS` as a **header** (not the `User-Agent` body field) is what
determines the JWT's audience — get this wrong and you get `success:true`
with `authentication_token: null`.

**Rate limit: ~6 requests/min per source IP** on this endpoint specifically
(not on `/accept` or `/start`). Pace logins accordingly when doing this for
many drivers at once; a script that pauses ~12s between logins stays under it
reliably. `/api/tasks/:id/accept` and `/api/tasks/:id/start` have **no**
comparable rate limit observed.

## Doing this for many drivers at once (setup vs. the actual test)

Steps 1 (create) and 2 (accept) can happen at any pace, sequentially, without
it mattering — they don't touch the pipeline under test. **Only step 3
(start) is the thing that should ever run as a deliberate, timed, parallel
burst** — that's the actual load-test event. Keep these phases separate in
tooling: build/accept everything first, confirm it's ready, then fire the
parallel `/start` calls as one explicit, confirmed step (e.g. via k6).

## Cleanup

Cancel a task (any status short of done): `cancel_task` action (`kmae04kd`)
via the same tokenized services API, `{"id": <task_id>}`.

Close a run without cancelling its tasks: `POST /runs/bulk_close` (above).
