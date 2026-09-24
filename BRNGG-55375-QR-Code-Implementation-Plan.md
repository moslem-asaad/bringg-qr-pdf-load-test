# BRNGG-55375 — QR Code / DeCA Document: Implementation Plan

Companion to [BRNGG-55375-QR-Code-Tech-Design.md](BRNGG-55375-QR-Code-Tech-Design.md) (design + verification) — this doc is the ordered, checkable build plan. Each phase below is a PR-sized unit; "Depends on" marks real blocking dependencies, everything else can start immediately in parallel.

Scope for this pass, per prior decisions: S2, S3 (Gotenberg mocked), S4, S6, S2.1. **Out of scope: S5 (regeneration), S7/S8/S11 (native + admin schema), S9 (E2E automation), the missing Article 6 fields (plate/NIF/special-auth — render blank).**

---

## Phase 0 — Schema (hagmonia, Rails) — **✅ DONE 2026-08-20, verified against the real dev DB**

Even though `documents`/`document_runs` are *written* by hagmonia-js, the DDL stays in hagmonia — it's the schema/`db/schema.rb` owner for this shared Postgres DB, same as every other table hagmonia-js co-writes today (`tasks`, `customers`, `way_points`).

- [x] Migration: create `documents` (id, merchant_id NOT NULL, type NOT NULL, token NOT NULL UNIQUE, upload_id NULL, failed_at NULL, failure_reason NULL, expires_at NULL, created_at, updated_at). Index on `token` (unique), index on `merchant_id`. — `db/migrate/20260820140000_create_documents.rb`.
- [x] Migration: create `document_runs` (id, document_id NOT NULL, run_id NOT NULL, created_at, updated_at). `UNIQUE (document_id, run_id)`, `INDEX (run_id)`. — `db/migrate/20260820140001_create_document_runs.rb`.
- [x] Migration: add `documents_configurations` — **⚠️ not symmetric, a real bug was caught and fixed here.** `merchant_configurations`: `jsonb, default: [], null: false` (top of the hierarchy). `team_configurations`: **plain nullable, no default** — `Team#get_team_configuration_for` falls back only on `nil`, and `[].nil?` is `false`; with `default: []` on both (the first version), the fallback never fired for any team. Verified broken, then verified fixed. — `db/migrate/20260820140002_...rb`.
- [x] JSON-schema validation on both columns — `app/validators/documents_configuration_validation.rb` (mirrors `GeocodingConfigurationValidation`, uses the existing `activerecord_json_validator` convention), wired into both `MerchantConfiguration` and `TeamConfiguration`. Not originally scoped, added after the user asked whether config columns need model-level validation.
- [x] Read-only models — **⚠️ not `Document`/`document.rb` as originally planned** — that name/file is already taken (`Document < TaskNote`, unrelated STI class). Actual model: `app/models/generated_document.rb`, `class GeneratedDocument < ApplicationRecord`, `self.table_name = "documents"`, **and `self.inheritance_column = nil`** (required — `type` is a plain string column here, not an STI discriminator). Derived `status` method lives here. Plus `app/models/document_run.rb`.
- [x] `Run` model: `has_many :document_runs`, `has_many :generated_documents, through: :document_runs, source: :document`.

Full detail, the bug writeup, and the ER diagram/worked example: [BRNGG-57146-S2-Documents-Schema-And-Read-Path.md](BRNGG-57146-S2-Documents-Schema-And-Read-Path.md) and [BRNGG-55375-QR-Code-Tech-Design.md](BRNGG-55375-QR-Code-Tech-Design.md) §1. Deploy this migration before Phase 3 goes live — Phase 1/2/4 can all be developed and reviewed in parallel with it.

---

## Phase 1 — `service-data` models (separate repo, `/Users/moslemasaad/bringg/service-data`)

**Depends on:** nothing to *write*, but the tables (Phase 0) must exist before this is *usable* at runtime.

- [x] `src/models/document.ts` — `class Document extends Model { get tableName() { return 'documents'; } }`. Override `save()`: on create only, `if (!this.get('token')) this.set('token', crypto.randomBytes(16).toString('base64url'))` — exact shape as [`SharedLocation.prototype.save`](../../../bringg/hagmonia-js/app/models/shared_location.js) (`hagmonia-js/app/models/shared_location.js:725-756`), sized to 128 bits (their example fields use `randomBytes(6)` — too small, don't copy that part). **`softDelete: false` is required** — this package's `RedisCache` plugin defaults every model's `softDelete` to `true` (for paranoia), and `documents` has no `delete_at` column; omitting the override breaks any relation fetch with a `column documents.delete_at does not exist` error (caught by actually running the tests, not by review).
- [x] `src/models/document_run.ts` — simple join model, `tableName: 'document_runs'`, `softDelete: false` (no `delete_at` column either).
- [x] Export both from `src/index.ts` (mirrored `MerchantConfiguration`/`TeamConfiguration`'s existing export lines, alphabetically between `Dispute` and `DriverAppUserSettings`).
- [x] Tests: `test/models/document.test.ts` (token generation, token immutability on update, derived `status`), `test/models/document_run.test.ts` (relation resolves) — all passing against the real local test DB (hagmonia's schema was already migrated there), plus the full existing 1303-test suite still green.
- [ ] Version bump + publish the package.
- [ ] Bump `hagmonia-js`'s `package.json` dependency to the new version, install.

---

## Phase 2 — hagmonia read side (S2 read half + S6) — **depends on Phase 0**

- [ ] `AnonymousController` subclass (mirror `oidc_controller.rb`) for `GET /document/:token`:
  - `documents.find_by(token:)` → `404` if not found.
  - Past `expires_at` → `410`.
  - `upload_id` nil (derived `pending`/`failed`) → `404`.
  - Artifact not retrievable (upload row gone / `findStored`-equivalent check fails) → `410`.
  - Otherwise: `Storage::UploadStorage#generate_content_url` → `302` with `Content-Disposition: attachment`.
  - `404`/`410` bodies must be human-readable, not raw JSON (an inspector hits this directly).
  - Log every resolution (token, outcome, source IP, timestamp).
- [ ] Authenticated `GET /runs/:id/document/:type` — merchant-scoped, `404` when absent.
- [ ] `Driver::RunSerializer`: add `documents` field — `[{id, type, status, url}]` when eligible + present, **absent (not `null`, not `[]`)** otherwise. `url` present only when `status == "ready"`.
- [ ] `Run.preload_for_serialization`: add the `documents` preload — this is the one place a missed preload becomes an N+1 on the hottest read path in the driver API (`batch_get`/`batch_get_with_open`/`unassigned`).
- [ ] Tests: `404`/`410`/`302` cases for the token endpoint, serializer shape test, an explicit query-count assertion against `batch_get_with_open` with multiple runs (N+1 regression guard).

---

## Phase 3 — hagmonia-js write side (S4 + write path) — **depends on Phase 0 (deployed) + Phase 1**

**✅ Decided 2026-08-22 — full detail in [BRNGG-57148-S4-Generation-Trigger-And-Write-Path.md](BRNGG-57148-S4-Generation-Trigger-And-Write-Path.md):**
1. **Lock mechanism: Redlock**, not `pg_advisory_xact_lock` — reuses the already-idiomatic pattern in `task_grouper.js`. Accepted tradeoff: a Redlock doesn't auto-release on a process crash (only via its own TTL), unlike a Postgres advisory lock — set the TTL deliberately and keep the `finally{unlock()}` unconditional.
2. **The no-automatic-retry gap is accepted for this pass.** Confirmed RabbitMQ never retries a failed handler (swallow-and-log at every layer) — combined with idempotent-create refusing to re-render a `failed` row, a failed generation is permanent until a human acts. Build the failure alert to say so explicitly, not "will retry."

- [ ] New handler module — **mirror `back_to_warehouse_app.js`'s registration shape, not `run_started.js`'s** (that one is a webhook with URL/config machinery this doesn't need; `back_to_warehouse_app.js` is a plain `BaseBringgApp` doing exactly "event in, config check, side effect").
- [ ] Config resolution: read `MerchantConfiguration`/`TeamConfiguration` via `service-data` for the run's merchant + team; team-overrides-merchant is a 2-line null-coalesce (`team.documents_configurations ?? merchant.documents_configurations`) — no Ruby helper to call from JS. **This only works because the team column is genuinely nullable with no default (fixed in Phase 0)** — JS's `??` has the identical nil-only fallback behavior as Ruby's `.nil?`; if this column ever defaulted to `[]`, `??` would never fire either.
- [ ] Match resolved config entries against `trigger === "run_started"`. No match → stop. **This is the entire eligibility gate — no separate flag anywhere.**
- [ ] Resolve the run's tasks — **no existing helper fits**, `Task.find`'s way_points ordering is per-task, not run-level. Model on `loading_ended.js`'s `fetchTasksByRunId` shape (`merchant_id`/`run_id`/`delete_at: null`, order by `priority`) — the epic requires including tasks "regardless of whether picked up or dropped off," so status must **not** be filtered like `getNotEndedTasksInRunByPriority` does (that excludes `done` and `cancelled`). **Explicitly decide whether cancelled tasks are included** — don't inherit silently.
- [ ] Idempotent claim, for each matching `{type, template_id}`, mirroring `task_grouper.js`'s `getOrCreateTaskGroupLeader` (this is the **primary defense against a confirmed real race**, not defensive boilerplate — `Run#start` in hagmonia has no locking around its `if started?` guard and is reachable from two independent call sites, so two genuine `run:started` publishes for the same run is an expected failure mode, not a rare edge case):
  1. `redlock.lock(lockKey, ttl)` — `lockKey` from `(run_id, type)`, `ttl` covering the templates-service call's own timeout.
  2. `SELECT` existing via `document_runs JOIN documents WHERE run_id = ? AND type = ?`.
  3. If found → return unchanged, stop (idempotent create — never re-render, even if `failed`; accepted, see the retry-gap note above).
  4. If not found → `Document.forge({merchant_id, type, run_id}).save()` (token generated by the model, Phase 1) → `INSERT document_runs (document_id, run_id)`.
  5. `finally { await lock.unlock(); }` — unconditional.
- [ ] Call templates-service with an **explicit timeout** — use `@bringg/service-utils`'s existing `direct_http` `Client` (retry/backoff built in, currently unused in hagmonia-js) rather than a raw call. Not optional: a hang doesn't stall other events, but leaves that document stuck claimed-but-unresolved indefinitely without one.
- [ ] On success (`upload_id` returned): `UPDATE documents SET upload_id = ?, failed_at = NULL`.
- [ ] On failure (templates-service error/timeout): `UPDATE documents SET failed_at = NOW(), failure_reason = ?` — **never** touch `upload_id`.
- [ ] Fire `documents_ready` (Phase 5) synchronously, same process, immediately after the successful update — no extra event hop.
- [ ] Run-end hook: add a second consumer on hagmonia-js's existing run-ended event handling (already consumed today for `run_ended.js`) — `UPDATE documents SET expires_at = run_end + 7 days` for any `documents` row linked to that run, if one exists.
- [ ] Tests: config merge (team overrides merchant, both absent, only one present), duplicate-trigger idempotency (two concurrent claims → one document), failure path leaves `upload_id` untouched, run-end sets `expires_at` only when a document exists.

---

## Phase 4 — templates-service render (S3, Gotenberg mocked) — **no dependencies, start immediately**

- [ ] Confirm/extend the existing `/render`-equivalent path to accept `template_id` selection for the `run_aggregation` template (the multi-task-in-one-doc rendering already works today — verified, no new context-builder needed).
- [ ] Add a clearly-isolated mock conversion step: HTML → "PDF" bytes, behind a single function/module (e.g. `htmlToPdf(html)`), tagged with a comment/TODO referencing BRNGG-57374 so swapping in the real Gotenberg-backed endpoint later is a one-function change, not a re-plumb. **Open, not blocking:** whether the real version becomes a new templates-service endpoint or a call to a separate service — don't design around either yet.
- [ ] Reuse the **existing** `UploadClient` RPC call (`@bringg/service-utils/lib/rpc_clients/upload`, already wired in `print_order_handler.ts:16` via `uploadClient.create(...)`/`.update(...)`) — store the mocked artifact as `application/pdf` (not `.html`, which is what the existing print-receipt flow stores) and return `{ upload_id }`.
- [ ] Tests: render returns one document for N task_ids with the mock conversion, `upload_id` returned, existing print-receipt flow unaffected (regression guard — this is a shared code path).

---

## Phase 5 — `documents_ready` webhook (hagmonia-js, S2.1) — **can be built independently, wired to Phase 3 at the end**

**⚠️ Blocked on a real decision, not just code — surfaced 2026-08-21 via the `#adeo_efti` Slack thread, escalated to a sync between Liel Armoza and the assignee.** The `documents` array item shape is settled; what wraps it (a `run` identifier, and whether order-level identifiers are also needed) is not. Full writeup, both options, and the reasoning: [BRNGG-57656-S2.1-DocumentsReady-Webhook.md](BRNGG-57656-S2.1-DocumentsReady-Webhook.md) and [BRNGG-55375-QR-Code-Tech-Design.md](BRNGG-55375-QR-Code-Tech-Design.md) §3a. Don't commit an envelope to ADEO before that sync happens.

- [ ] `app/services/webhooks/documents_ready.js` extending `BaseWebhook`, `baseModel: 'run'` — this is just a label, it does **not** mean reusing `run_ended.js`'s heavy `Run.serializeToWebhook`/`Task.serializeToWebhook` path (~89 fields/task, verified). Modeled directly on `questionnaire_response_submitted.js`'s flexible-attribute pattern instead.
- [ ] `flexibleModelConfig()` for the new `documents` attribute, plus reuse the **existing** light `case 'run':` attribute (`base_webhook.js:349-357`, backed by `RunDataService`) for the run/order identifiers — **do not write new fetch code for this part**, just configure `fields`/`relations`.
- [ ] **Pending Liel/ADEO's answer:** `fields: ['id', 'external_id']` on `run`, either with no `relations` (Option A, run-only) or `relations: [{name: 'tasks', fields: ['id', 'external_id']}]` (Option B, adds order identifiers nested inside `run`).
- [ ] New `case 'documents':` branch in `fetchWebhookData` (`base_webhook.js`) + a small fetch/serializer producing `[{id, type, status, url}]` — **must call the same derived-status logic Phase 2/3 use**, not recompute it independently (S2 AC 21 — the one thing that makes S6's payload and this webhook's payload provably identical). This part needs Phase 1's `Document`/`DocumentRun` service-data models to query against.
- [ ] Register in `app/services/webhooks/index.js`.
- [ ] Absent-not-empty semantics: when `documents` isn't selected or the entity has no document, the key is absent — never `[]`.
- [ ] Tests: payload shape parity test against Phase 2's serializer output for the same document (byte-for-byte shape match), unknown-`type` values ignored per the forward-compat requirement.

---

## Phase 6 — Integration smoke test (manual, before calling this done)

- [ ] Set `documents_configurations` on a test merchant/team: `[{"trigger": "run_started", "documents": [{"type": "run_aggregation", "template_id": <test id>}]}]`.
- [ ] Start a multi-stop route on that merchant → confirm: `documents` row reaches `ready`, `document_runs` linked, `documents_ready` webhook fires to a test endpoint.
- [ ] Call `batch_get_with_open` for the run → confirm `documents` present with a `/document/:token` URL, no signature params in it.
- [ ] Open the token URL in a private window → PDF downloads directly, no auth.
- [ ] Alter one character of the token → `404`.
- [ ] Start a route on a merchant/team with **no** matching config entry → confirm nothing is created, no webhook, `documents` key absent from the driver payload.
- [ ] (Manually, or via a fixture) push `expires_at` into the past → confirm `410`, not `302`.

---

## Suggested PR order

1. Phase 0 (hagmonia migrations + read-only models) — merge & deploy first, nothing else depends on its *code* but Phase 3 needs it *deployed*.
2. Phase 1 (service-data) and Phase 4 (templates-service) — fully parallel, no cross-dependency.
3. Phase 2 (hagmonia read endpoints + S6) — parallel with Phase 3, both only need Phase 0.
4. Phase 3 (hagmonia-js write path) — needs Phase 0 deployed + Phase 1 published + Phase 4 available (or a stubbed response during dev).
5. Phase 5 (webhook) — can be coded anytime, wire the live call into Phase 3 last.
6. Phase 6 — after everything above is deployed together.
