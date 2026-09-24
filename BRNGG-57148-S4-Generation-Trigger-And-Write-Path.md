# BRNGG-57148 (S4) — generation trigger + write path (hagmonia-js)

Part of [BRNGG-55375](https://bringg.atlassian.net/browse/BRNGG-55375). Full rationale in [BRNGG-55375-QR-Code-Tech-Design.md](BRNGG-55375-QR-Code-Tech-Design.md) §1/§2. **Rewritten 2026-08-22 after a dedicated deep-research pass. Both decisions below are now settled (2026-08-22): lock mechanism → Redlock; the no-automatic-retry gap → accepted for this pass.**

**Repo:** `hagmonia-js`. **Depends on:** BRNGG-57146's migration deployed + the service-data prerequisite ticket published/bumped + BRNGG-57147 (S3, or a stub during dev). **Blocks:** BRNGG-57656 (S2.1) firing correctly, since S2.1 fires from the end of this chain.

## ⚠️ Read first

- **Open #5 (where does the listener live?) → hagmonia-js**, but the precedent to copy is `back_to_warehouse_app.js`, not `run_started.js`. `run_started.js` is a *webhook* (URL/condition/merchant-webhook-config machinery you don't need). `back_to_warehouse_app.js` (`lib/bringg_apps/back_to_warehouse_app.js:23-80`) is a plain `BaseBringgApp` subclass that registers directly for `RUN_STARTED` and does a config-check-then-side-effect — structurally identical to what this story needs, since `documents_configurations` lives on plain `MerchantConfiguration`/`TeamConfiguration`, not on an `ApplicationMerchantConfiguration` the webhook machinery expects.
- **Open #1 (does a run-level route-started event exist?) → yes.** `Run#notify_run_started` (`hagmonia/app/models/run.rb:372-387`) already publishes `run:started` over RabbitMQ. Nothing new needed on the hagmonia side.
- **Open #2 (the eligibility configuration doesn't exist) → resolved.** It's `documents_configurations`. Having a matching config entry for the fired trigger **is** eligibility.
- **Scope widened:** this story owns the create/write path too (BRNGG-57146's original write-path ACs), since this is the only caller and both live here.

## ✅ Decided 2026-08-22 — Redlock, and the retry gap is accepted for this pass

**Lock mechanism: Redlock, not `pg_advisory_xact_lock`.** Reuses the already-idiomatic, already-tested pattern for exactly this "claim before create across processes" problem — `app/services/task/task_grouper.js:16-91`'s `getOrCreateTaskGroupLeader` (lock → check-if-exists → create → unlock in a `finally`), also used in `auto_breaks_app.js`/`external_fleet_app.js`. **Known, accepted tradeoff:** unlike a Postgres advisory lock, a Redlock is not released automatically by a process crash between lock and unlock — it only expires via its own TTL. Set that TTL deliberately (long enough to cover the templates-service call including its timeout from step 6, short enough that a crashed worker doesn't block reclaiming that `(run_id, type)` for an unreasonable window) and make sure the `finally { lock.unlock() }` is unconditional, mirroring `task_grouper.js` exactly.

**The no-automatic-retry gap is accepted for this pass — build it as intentional silence, not as an omission to fix later by accident.** Confirmed (traced the full chain: `AppSubscriber.executeCallback` → `processJobs`'s `Promise.allSettled` → `onBackgroundTask`'s own try/catch → the underlying `arnavmq` consumer) that an error at any layer is caught, logged, and reported to Airbrake — never rethrown, so RabbitMQ never nacks/requeues, and the message is always acked regardless of handler outcome. Combined with the idempotent-claim rule (a duplicate `run:started` for an already-claimed `(run_id, type)` returns the existing row **untouched, even if `failed`**, per step 5) — **once a document reaches `failed`, nothing in this design retries it, ever, for this pass.** This is the same gap the tech design doc already flagged as unowned (epic AC 11) — now confirmed as real, verified behavior rather than a theoretical risk. **Since this is accepted rather than fixed:** the alert fired on a `failed` document (step 8) must say so explicitly — not "will retry," a human action item. Don't build any code that implies retry is coming; that would be misleading given what's actually true.

## Chain this ticket owns, end to end

```
run:started (Rabbit) → AppSubscriber consumes (back_to_warehouse_app.js-style registration)
  → read documents_configurations (merchant+team, team overrides merchant via `??`)
  → no match? stop.
  → match: resolve run's tasks (bespoke query — no existing helper fits, see below)
      → Redlock claim → INSERT documents (pending) + document_runs
      → call templates-service (with an explicit timeout — required, see below)
      → on success: UPDATE documents SET upload_id, failed_at = NULL
      → on failure: UPDATE documents SET failed_at, failure_reason — permanent until a human/reconciliation acts (see the retry gap above)
      → fire documents_ready (S2.1), same process
run:ended (Rabbit, already consumed today for run_ended.js)
  → UPDATE documents SET expires_at = run_end + 7 days
```

## Steps

1. **New handler, registered for `RUN_STARTED`** via `registerQueue(AppSubscriber.REGISTRATION_TYPES.RUN_STARTED, this.onRunStarted)` — the `back_to_warehouse_app.js` shape, not `run_started.js`'s webhook shape.

2. **Config resolution** — `team.documents_configurations ?? merchant.documents_configurations`. Confirmed this only works because `team_configurations.documents_configurations` is genuinely nullable with no default (BRNGG-57146's fix). **Also confirmed: the JSON-schema validator deliberately puts no `enum` constraint on `trigger`** (`app/validators/documents_configuration_validation.rb`, everything else in that schema is strict — `additionalProperties: false`, explicit `required` — the omission on `trigger` specifically is evidence future trigger types are anticipated). Write the match as a generic `entry.trigger === RUN_STARTED_TRIGGER_CONSTANT` filter over the array, don't assume the array only ever contains one kind of entry.

3. **Match** resolved config entries against the trigger. No match → stop. Entire eligibility gate.

4. **Resolve the run's tasks — no existing helper is a drop-in fit, this needs a bespoke query.** Checked every candidate in this codebase:
   - `Run.getNotEndedTasksInRunByPriority` — orders by `priority`, but excludes `done` **and** `cancelled` tasks. Wrong for this feature — the epic's own text says the report must cover "every task attached to the route — regardless of whether it's been picked up or dropped off yet," i.e. completed tasks must be included.
   - `Run.getTaskInRunByOrder` / `Run.getLastTaskByEtl` — order by actual checkout time / ETL, not planned route order.
   - `loading_ended.js`'s `fetchTasksByRunId` — the closest fit: `Task.query(qb => qb.where({merchant_id, run_id, delete_at: null})).orderBy('priority', 'asc')`. Excludes soft-deleted tasks explicitly (required — nothing does this by default), applies no status filter at all.
   - **Recommendation: model the query on `fetchTasksByRunId`'s shape** (matches the epic's "regardless of status" requirement) — but **explicitly decide whether cancelled tasks should be included**, since the epic's text doesn't address that case directly and neither does this precedent's lack of a filter necessarily mean "correct for us," just "happens to have none." Don't inherit this silently — write down the decision.

5. **Idempotent claim**, per matching `{type, template_id}`, mirroring `task_grouper.js`'s `getOrCreateTaskGroupLeader` exactly:
   1. `redlock.lock(lockKey, ttl)` — `lockKey` derived from `(run_id, type)`; `ttl` long enough to cover step 6's templates-service call including its own timeout.
   2. Check existing via `document_runs JOIN documents WHERE run_id = ? AND type = ?`.
   3. Found → return unchanged, stop. **Never re-render on a duplicate trigger, even if `failed`** — this is deliberate (the retry gap above is accepted, not an oversight).
   4. Not found → `Document.forge({merchant_id, type, run_id}).save()` → `INSERT document_runs`.
   5. `finally { await lock.unlock(); }` — unconditional, same as the precedent.

   **This claim is load-bearing, not defensive-programming boilerplate.** Confirmed a real, reachable duplicate-publish race in hagmonia itself: `Run#start` (`hagmonia/app/models/run.rb:298-312`) has an `if started?` guard but **no `with_lock`/pessimistic locking** around the check-then-update, and it's reachable from two independent call sites (`user.rb:501`, `task.rb:3369`). Two concurrent calls can both pass the guard before either commits, both write `started_at`, and **both legitimately publish `run:started` for the same run.** This is the expected failure mode this story must handle, not a rare corner case — the idempotent claim is the *only* thing preventing a duplicate document.

6. **Call templates-service with an explicit, short timeout.** Confirmed no HTTP client with retry/timeout exists in hagmonia-js today, but one already exists, unused, in the shared package: `@bringg/service-utils`'s `direct_http` `Client`/`RetryOptions` (`service-utils/src/lib/clients/direct_http/client.ts`), defaulting to a 10s timeout, 3 retries, exponential backoff, retryable on `408/500/502/503/504`. **Use this rather than a raw HTTP call.** Why the timeout is non-optional, not just good practice: a hang doesn't stall the rest of the event pipeline (Node's event loop keeps processing other messages up to the channel's prefetch limit), but it *does* leave that one document permanently claimed-but-unresolved for as long as the hang persists — and per the retry-gap above, once it eventually does fail, nothing retries it.

7. **On success**: `UPDATE documents SET upload_id = ?, failed_at = NULL`.

8. **On failure** (including a timeout from step 6): `UPDATE documents SET failed_at = NOW(), failure_reason = ?`. **This is now understood to be effectively permanent for this run/type** absent a human or a future reconciliation job — make sure whatever alerting this triggers reflects that (not "will retry," because it won't).

9. **Fire `documents_ready`** (BRNGG-57656) synchronously, same process. **Pass the in-hand document object directly** — per S2.1's own research, don't have the webhook re-fetch it by ID through a cache-mediated path.

10. **Run-end hook** — second consumer on the existing run-ended handling: `UPDATE documents SET expires_at = run_end + 7 days` for any linked `documents` row.

## Tests

- Config merge: team overrides merchant, only merchant set, only team set, neither set (→ no-op), team explicitly empty (`[]`, not `null`) → no fallback, correctly treated as "explicitly off."
- **Duplicate-publish race, not just duplicate-trigger idempotency**: two concurrent `run:started`-equivalent calls for the same run (simulating the confirmed hagmonia-side race, not just a retried message) → exactly one `documents` row.
- A `failed` document does not get re-rendered by a second matching trigger — assert this explicitly, since it's a deliberate (and consequential) design choice, not incidental behavior.
- Task resolution excludes soft-deleted tasks; explicit test for whether cancelled tasks are included or excluded, per whatever gets decided in step 4.
- templates-service call timeout is enforced — a call that never resolves still results in a `failed` document within a bounded time, not an indefinitely stuck `pending` one.
- Zero tasks on the run at trigger time — explicit decision test (skip vs. generate empty), not left implicit.

## Acceptance criteria

1. Starting a route on a configured merchant/team produces exactly one `documents` row reaching `ready` or `failed` within the templates-service call's bounded timeout.
2. Starting a route on an unconfigured merchant/team creates nothing — no row, no webhook.
3. A duplicate `run:started` for the same run (whether from a genuine hagmonia-side race or any other cause) never creates a second document.
4. `expires_at` is set to run end + 7 days when the run ends, and only if a document exists.
5. A `failed` document is understood and documented as not self-healing — the alert/log for it must not imply an automatic retry will happen.
