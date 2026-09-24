# BRNGG-55375 — DocumentsApp Test Cases

All branches through `hagmonia-js`'s `DocumentsApp.onRunStarted` (`lib/bringg_apps/documents_app.js`),
with the exact expected log lines for each. Log prefix is `DocumentsApp onRunStarted` or
`DocumentsApp generateDocument`, each tagged with `{merchant_id, run_id, request_id}`.

Use the `/automation/*` backdoor endpoints (see
[BRNGG-55375-QA-Test-Session-Log.md](BRNGG-55375-QA-Test-Session-Log.md)) to set up each case, then
trigger `run:started` via `PATCH /automation/run/:id` with a changed `started_at`.


| #   | Case                                           | How to set up                                                                                                                                                                                                                                | Expected log sequence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Side effects                                                                  |
| --- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 1   | **Happy path**                                 | Matching config, run has tasks, no prior document                                                                                                                                                                                            | `DocumentsApp onRunStarted called` → (render+upload succeed) → `sendWebHook - was done for https://webhooks-debug.bringg.dev/...` (from `webhook_app.js`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | New `uploads` row, webhook delivered                                          |
| 2   | **No matching config**                         | Clear/unset `documents_configurations` on the merchant, or set a config with `trigger` ≠ `"run_started"`                                                                                                                                     | `DocumentsApp onRunStarted called` → `DocumentsApp onRunStarted no matching documents_configurations trigger, halting`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | None                                                                          |
| 3   | **Team override to empty**                     | Set `TeamConfiguration.documents_configurations = []` for the run's team while the merchant's config is still non-empty (tests that `??` only falls back on `nil`, not on `[]`)                                                              | Same as #2 — `no matching documents_configurations trigger, halting`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | None                                                                          |
| 4   | **Run has no tasks**                           | Trigger on a run with zero non-deleted tasks (or soft-delete all of the run's tasks first)                                                                                                                                                   | `DocumentsApp onRunStarted called` → `DocumentsApp onRunStarted run has no tasks, halting`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | None                                                                          |
| 5   | **Config matches but** `documents: []`         | Set `documents_configurations: [{"trigger": "run_started", "documents": []}]`                                                                                                                                                                | `DocumentsApp onRunStarted called` — and nothing else (the loop over `config.documents` iterates zero times; there's no explicit halt log for this branch, so "called" with no follow-up is itself the signature)                                                                                                                                                                                                                                                                                                                                                                                                                                                               | None                                                                          |
| 6   | **Already stored (idempotent skip)**           | Trigger again on a run that already has a stored `runAggregation` upload                                                                                                                                                                     | `DocumentsApp onRunStarted called` → `DocumentsApp generateDocument document already stored, skipping`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | None (no new row, no webhook)                                                 |
| 7   | **templates-service unreachable / RPC throws** | Stop templates-service (or block the queue) before triggering                                                                                                                                                                                | `DocumentsApp onRunStarted called` → `DocumentsApp generateDocument templates-service render call failed` (level **error**, includes the thrown error)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | None — no partial `uploads` row, no webhook                                   |
| 8   | **templates-service returns** `success: false` | Harder to force manually — e.g. point at a merchant with no `print_order` template resolvable, or a templates-service bug returning `{success: false, error, message}`                                                                       | `DocumentsApp onRunStarted called` → `DocumentsApp generateDocument templates-service render returned failure` (level **error**, includes `response.error`/`response.message`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | None                                                                          |
| 9   | **Concurrent duplicate** `run:started` (race)  | Fire two `run:started` events for the same run+type back-to-back before the first completes — needs a small script issuing two near-simultaneous triggers, or replaying the queue message; a single sequential `PATCH` cannot reproduce this | Winner: same as #1. Loser: blocks on `redlock.lock('documents:<run_id>:<type>', ...)` until the winner's `finally { lock.unlock() }` releases it, then finds the just-created row → `DocumentsApp generateDocument document already stored, skipping`. If contention outlasts Redlock's retry budget (~10 retries × 200ms ± jitter, roughly 2–4s) while the winner is still mid-RPC (up to 20s timeout), the loser's `redlock.lock(...)` call itself can throw — that happens *before* the `try/finally`, so it propagates up and gets caught one level higher, in `AppSubscriber.executeCallback`: `executeCallback - DocumentsApp - run:started - failed with LockError: ...` | Exactly one `uploads` row, exactly one webhook delivery regardless of outcome |
| 10  | **Run's only tasks are cancelled**             | Decided answer to the "cancelled tasks?" open question: `PATCH /automation/task/:task_id` on every task on the target run — `changes: {status: 7}` (cancelled) — then trigger `run:started`                                                | `DocumentsApp onRunStarted called` → `DocumentsApp onRunStarted run has no tasks, halting` (same halt as #4 — cancelled tasks are excluded from `resolveRunTaskIds`, so the run reads as having zero tasks)                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | None                                                                          |
| 11  | **Cancelled task alongside an active one**     | Run has one active task and one cancelled task (`status: 7`), matching config                                                                                                                                                                | Same as #1, but `task_ids` in the RPC request to templates-service contains only the active task's id, not the cancelled one's                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | New `uploads` row covering only the active task, webhook delivered           |




## Notes

- Cases 1, 6, 7, 8 can reuse the same run repeatedly. Cases 2–5 require temporarily mutating
`documents_configurations`/tasks via the `/automation/*` endpoints — restore the working config
afterward so the state doesn't regress.
- A repeated `PATCH /automation/run/:id` with the *same* `started_at` value is a no-op at the
hagmonia model layer (`saved_change_to_started_at?` is `false`), so no `run:started` event
publishes at all — always use a new timestamp to force a fresh trigger.



## Checklists



### 1. Happy path

- [x] Confirm `documents_configurations` on the merchant (or team) has `trigger: "run_started"` with
  ```
  `documents: [{"type": "runAggregation"}]`
  ```
- [x] Confirm `DocumentsApp` is installed for the merchant (`applications_merchants` row present)
- [x] Confirm the target run has ≥1 non-deleted task
- [x] Confirm no existing `uploads` row for `record_type='Run', record_id=<id>, attachment_type='runAggregation'`
- [x] `PATCH /automation/run/:id` with a new `started_at`
- [x] Kibana: `DocumentsApp onRunStarted called`
- [x] Kibana: no halting log lines (no "no matching...", no "run has no tasks...")
- [x] Kibana: `sendWebHook - was done for https://webhooks-debug.bringg.dev/...`
- [x] Webhook debug page: new POST received with `{run, documents}` payload
- [x] DB: new `uploads` row with `stored_at` set
- [x] `has_document` SQL check (see [BRNGG-55375-QA-Test-Session-Log.md](BRNGG-55375-QA-Test-Session-Log.md)) returns `true`



### 2. No matching config

- [x] `POST /automation/merchant_configuration/upsert` — set `documents_configurations: []` (or a
  ```
  config with `trigger` ≠ `"run_started"`)
  ```
- [x] `PATCH /automation/run/:id` with a new `started_at`
- [x] Kibana: `DocumentsApp onRunStarted called`
- [x] Kibana: `DocumentsApp onRunStarted no matching documents_configurations trigger, halting`
- [x] DB: no new `uploads` row
- [x] Webhook debug page: no new delivery
- [x] Restore `documents_configurations` to the working value from case 1



### 3. Team override to empty

- [x] Confirm the merchant-level `documents_configurations` is still the working (non-empty) config
- [x] `POST /automation/team_configuration/upsert` — `query: {merchant_id, team_id}`,
  ```
  `attributes: {documents_configurations: []}`
  ```
- [x] `PATCH /automation/run/:id` with a new `started_at` (run must belong to that team)
- [x] Kibana: `DocumentsApp onRunStarted called`
- [x] Kibana: `DocumentsApp onRunStarted no matching documents_configurations trigger, halting`
- [x] DB: no new `uploads` row
- [x] Webhook debug page: no new delivery
- [x] Restore/remove the team-level override afterward (`documents_configurations: null`, not `[]`,
  ```
  so the merchant fallback resumes — `[].nil?` is `false` in the `??` fallback)
  ```



### 4. Run has no tasks

- [x] `PATCH /automation/task/:task_id` for every task on the target run — `changes: {delete_at: "<now>"}`
- [x] `PATCH /automation/run/:id` with a new `started_at`
- [x] Kibana: `DocumentsApp onRunStarted called`
- [x] Kibana: `DocumentsApp onRunStarted run has no tasks, halting`
- [x] DB: no new `uploads` row
- [x] Webhook debug page: no new delivery
- [x] Restore the tasks afterward (`changes: {delete_at: null}`) if reusing this run for other cases



### 5. Config matches but `documents: []`

- [ ] `POST /automation/merchant_configuration/upsert` — `documents_configurations: [{"trigger": "run_started", "documents": []}]`
- [ ] `PATCH /automation/run/:id` with a new `started_at`
- [ ] Kibana: `DocumentsApp onRunStarted called`
- [ ] Kibana: confirm **no** further `DocumentsApp` log line at all (no halt message, no `generateDocument` line)
- [ ] DB: no new `uploads` row
- [ ] Webhook debug page: no new delivery
- [ ] Restore `documents_configurations` to the working value from case 1



### 6. Already stored (idempotent skip)

- [x] Confirm the run already has a stored `uploads` row for `attachment_type='runAggregation'`
- [x] `PATCH /automation/run/:id` with a new (different) `started_at`
- [x] Kibana: `DocumentsApp onRunStarted called`
- [x] Kibana: `DocumentsApp generateDocument document already stored, skipping`
- [x] DB: still exactly **one** `uploads` row for that run+type (no duplicate created)
- [x] Webhook debug page: no new delivery



### 7. templates-service unreachable / RPC throws

- [x] Stop templates-service (or otherwise block its RPC queue) in the QA namespace
- [x] Use a run/attachment_type combination with no existing stored document
- [x] `PATCH /automation/run/:id` with a new `started_at`
- [x] Kibana: `DocumentsApp onRunStarted called`
- [x] Kibana: `DocumentsApp generateDocument templates-service render call failed` (level **error**)
- [x] DB: no `uploads` row created (no partial state)
- [x] Webhook debug page: no delivery
- [ ] Restart templates-service afterward and confirm case 1 still passes



### 8. templates-service returns `success: false`

- [x] Set up a condition that makes templates-service return `{success: false, error, message}`
  ```
  (e.g. a merchant with no resolvable `print_order` template)
  ```
- [x] `PATCH /automation/run/:id` with a new `started_at`
- [x] Kibana: `DocumentsApp onRunStarted called`
- [x] Kibana: `DocumentsApp generateDocument templates-service render returned failure` (level
  ```
  **error**, includes `response.error`/`response.message`)
  ```
- [x] DB: no `uploads` row created
- [x] Webhook debug page: no delivery
- [ ] Revert whatever induced the failure



### 9. Concurrent duplicate `run:started`

- [x] Use a run/attachment_type combination with no existing stored document
- [x] Prepare a script/mechanism to fire two `run:started` triggers for the same run in quick
  ```
  succession (a single sequential `PATCH` cannot reproduce this — the second `started_at` change
  needs to land while the first is still mid-flight)
  ```
- [x] Fire both triggers
- [x] Kibana: two `DocumentsApp onRunStarted called` lines
- [x] Kibana: exactly one full render/webhook path completes
- [x] Kibana: the other shows either `DocumentsApp generateDocument document already stored, skipping`
  ```
  or (if contention outlasts Redlock's retry budget) `executeCallback - DocumentsApp - run:started - failed with LockError: ...`
  ```
- [x] DB: exactly **one** `uploads` row for that run+type
- [x] Webhook debug page: exactly **one** delivery



### 10. Run's only tasks are cancelled

- [ ] `PATCH /automation/task/:task_id` for every task on the target run — `changes: {status: 7}`
- [ ] `PATCH /automation/run/:id` with a new `started_at`
- [ ] Kibana: `DocumentsApp onRunStarted called`
- [ ] Kibana: `DocumentsApp onRunStarted run has no tasks, halting`
- [ ] DB: no new `uploads` row
- [ ] Webhook debug page: no new delivery
- [ ] Restore the tasks afterward (`changes: {status: 0}`) if reusing this run for other cases



### 11. Cancelled task alongside an active one

- [ ] Ensure the run has at least one active task (any non-cancelled status)
- [ ] `PATCH /automation/task/:task_id` on a second task on the same run — `changes: {status: 7}`
- [ ] `PATCH /automation/run/:id` with a new `started_at`
- [ ] Kibana: `DocumentsApp onRunStarted called` → (render+upload succeed) → webhook delivered, same as #1
- [ ] Confirm (e.g. via the `render:print_order` RPC request — `format: pdf` — logged by templates-service, or the resulting PDF's content) that `task_ids` includes only the active task, not the cancelled one