# BRNGG-55375 - Driver App QR Code for DeCA Compliance Documents - Design Document

*Adapted from the single-task design-doc template to epic scope, per explicit override - this epic spans 4 services and ~7 stories, not one task. The Business Logic Baseline / Trace Map prerequisite gate was skipped for the same reason (no single task context file exists for an epic).*

## 1. Task Overview

- **Jira:** [BRNGG-55375](https://bringg.atlassian.net/browse/BRNGG-55375) - epic
- **Title:** Driver App QR Code Display for Digital Transport Documents
- **Type:** Epic (feature), spanning stories S2 ([BRNGG-57146](https://bringg.atlassian.net/browse/BRNGG-57146)), S3 ([BRNGG-57147](https://bringg.atlassian.net/browse/BRNGG-57147)), S4 ([BRNGG-57148](https://bringg.atlassian.net/browse/BRNGG-57148)), S2.1 ([BRNGG-57656](https://bringg.atlassian.net/browse/BRNGG-57656)), S6 ([BRNGG-57150](https://bringg.atlassian.net/browse/BRNGG-57150)), plus the service-data prerequisite ([BRNGG-57886](https://bringg.atlassian.net/browse/BRNGG-57886))
- **Priority:** High - hard legal deadline
- **Environment:** Production, all merchants operating in Spain
- **Services:** hagmonia, hagmonia-js, service-data, templates-service, upload-service (read-only), Driver App (Android/iOS, contract only)

**Problem statement:** Spain's Sustainable Mobility Law 9/2025 requires the transport document (DeCA) to be digital and scannable via QR code from **5 October 2026**. Today the Driver App has no route-level compliance document and no QR code - drivers carry no scannable proof of the transport contract, and Bringg has no mechanism to generate, store, retain, or notify a merchant's system (e.g. ADEO) about one.

## 2. Investigation Summary

### Current Behavior

1. A route starts -> `Run#notify_run_started` (`hagmonia/app/models/run.rb:370-385`) already publishes a `run:started` event over RabbitMQ. **Verified in code** - this is not new infrastructure.
2. `hagmonia-js` already consumes this exact event shape for other features (`back_to_warehouse_app.js`, `realtime_eta_app.js`, and `app/services/webhooks/run_started.js` - the closest structural precedent: event in -> read merchant config -> external side effect).
3. `templates-service`'s `POST /v1/print-order/render` (`app/controllers/v1/print_order.ts`) already accepts multiple `task_ids` and produces **one combined HTML document** with page breaks between tasks (`PrintOrderHandler.renderHtml()`) - this is the existing print-receipt flow, reused rather than rebuilt.
4. `templates-service` has **no server-side PDF generation at all** - no `puppeteer`/`pdf-lib`/`gotenberg`/`wkhtmltopdf` in its dependencies. Everything today ends at HTML, relying on browser print-to-PDF.
5. `hagmonia` has **no background-job runtime** (no Sidekiq, no ActiveJob - confirmed absent from the Gemfile). Its only execution model is sync request/response plus outbound Rabbit publish.
6. `hagmonia-js` already writes directly into core, Rails-owned, validated tables via `@bringg/service-data`, bypassing Rails validation - e.g. `Task.forge({id, merchant_id, teams_ids}).save({done_processing: true}, {patch: true})` (`hagmonia-js/app/events/app_subscriber.js:318`) and `Task#destroy({softDelete: true})` -> `this.save({delete_at: new Date()})` (`hagmonia-js/app/models/task.js:80-84`).
7. `hagmonia`'s existing `Storage::UploadStorage#generate_content_url` (`hagmonia/app/services/storage/upload_storage.rb:15`) already signs storage URLs directly via Fog for other upload types (photos/signatures) - not a novel pattern.
8. No `documents`/`document_runs` table, no `Document`/`DocumentRun` model, and no `documents_configurations` config column existed anywhere before this epic (verified against `db/schema.rb` and `service-data`'s `src/models/`).

### Expected Behavior

A route start triggers, per merchant/team configuration, generation of a route-level PDF document; the document is stored, retained for 7 days past route end, exposed to the Driver App offline via the run payload, scannable by a roadside inspector via a token-guarded URL, and reported to the merchant's own systems via a webhook.

### Root Cause (gap analysis)

No existing Bringg mechanism covers a **route-level**, **retained**, **externally-scannable**, **merchant-notified** document. The nearest analogs don't fit:
- `Document` (`hagmonia/app/models/document.rb`) is an STI subtype of `TaskNote` - **task-level**, not route-level, and has no token/retention/webhook concept.
- The existing print-receipt flow (`templates-service`) produces HTML for on-demand viewing, not a retained, tokenized, roadside-scannable artifact.

### Key Findings

- `Run#notify_run_started` already exists (`hagmonia/app/models/run.rb:370-385`) - S4's original open question ("does a run-level event exist?") is answered, no new event needed.
- `templates-service`'s render endpoint already does the hard part (multi-task, one combined HTML doc) - `Vehicle` (plate/trailer) is the real gap: never fetched into the render context today (`templates-service/.../print_order_handler.ts:214-338`).
- No hardcoded shipper NIF (`B84406289`) found anywhere in `templates-service` - don't assume it exists as a fallback.
- The "existing ~7-day retention pattern" the epic assumes is **not implemented anywhere** - `uploads.ttl` is a real nullable column but nothing sets a default and no existing caller passes one.
- `hagmonia-js` does not sign webhook delivery URLs (a prior ticket's premise was wrong) - only asset URLs embedded in payloads.
- No generic "team overrides merchant" resolver exists for the config family this epic actually needs (`MerchantConfiguration`/`TeamConfiguration`, not the Application-scoped AMC/ATC family) - `Team#get_team_configuration_for` (`hagmonia/app/models/team.rb:203-208`) covers it for free, but only for column-backed attributes.

## 3. Proposed Solution

### Approach

Split by data-access reality, not by feature boundary: `hagmonia` owns the schema and reads (it's the system of record and already exposes the Driver App payload); `hagmonia-js` owns the entire write path (trigger, config gate, idempotent claim, render call, webhook) because it already writes into hagmonia's Postgres today and hagmonia has no job runtime to do this itself.

### Technical Design

```
[Driver starts route]
        |
        v
[hagmonia] Run#notify_run_started
  app/models/run.rb:370-385  (EXISTING - publishes "run:started" via RabbitMQ)
        |
        v
[RabbitMQ]  "run:started"
        |
        v
[hagmonia-js]  🆕 NEW handler (mirrors EXISTING app/services/webhooks/run_started.js)
        |
        v
  +---------------------------------------------------------------+
  |  ELIGIBILITY GATE                                              |
  |  read MerchantConfiguration + TeamConfiguration                |
  |    service-data: src/models/merchant_configuration.ts (EXIST.) |
  |                  src/models/team_configuration.ts (EXISTING)   |
  |  merge: team.documents_configurations ?? merchant.…             |
  |    🆕 NEW, 2-line null-coalesce inside the new handler          |
  +---------------------------------------------------------------+
        |
        +---- no matching "trigger" entry ---------> [STOP, nothing generated]
        |
        v  (trigger "run_started" matches)
  +---------------------------------------------------------------+
  |  IDEMPOTENT CLAIM                                              |
  |  redlock.lock(`documents:${run_id}:${type}`)                   |
  |    🆕 NEW - mirrors EXISTING task_grouper.js claim pattern      |
  |  check DocumentRun WHERE run_id = ?                            |
  |    service-data: src/models/document_run.ts  (BUILT, this epic)|
  +---------------------------------------------------------------+
        |
        +---- already claimed ----------------------> [return existing Document, unchanged]
        |
        v  (not yet claimed)
  Document.forge({merchant_id, type}).save()
    service-data: src/models/document.ts:27-33  (BUILT, this epic -
    save() override generates a 128-bit token via crypto.randomBytes(16))
        |
        v
  DocumentRun.forge({document_id, run_id}).save()
    service-data: src/models/document_run.ts  (BUILT, this epic)
        |
        v
  redlock.unlock()  (finally, unconditional)
        |
        v
[hagmonia-js] --POST /render {task_ids, template_id}--> [templates-service]
        |
        v
[templates-service]  app/controllers/v1/print_order.ts  (EXISTING, extended
  with a 🆕 NEW template_id branch)
  PrintOrderHandler.renderHtml()  (EXISTING - already combines multiple
  task_ids into one HTML doc, page-break-after between tasks)
        |
        v
  HTML -> PDF conversion   🆕 MOCKED (real conversion blocked on Gotenberg,
                            BRNGG-57374, no due date)
        |
        v
  upload-service client  (EXISTING - print_order_handler.ts already uploads
  and returns {upload_id} for the current print-receipt flow)
        |
        v  upload_id
[hagmonia-js]  Document.forge({id}).save({upload_id}, {patch: true})
  service-data: src/models/document.ts  (BUILT - status getter derives to
  "ready" once upload_id is set)
        |
        v
[hagmonia-js]  fire "documents_ready" webhook
  🆕 NEW case in app/services/webhooks/base_webhook.js:349-367
  (EXISTING flexible-attribute dispatch - the 'run' case is already shipped
  and tested via optimization_applied.js)
        |
        v
[Merchant webhook endpoint, e.g. ADEO]


--- separately, any time after generation ---

[Driver App] --GET batch_get_with_open--> [hagmonia]
  Api::V2::RunsController  (EXISTING)
        |
        v
  Run.preload_for_serialization
    app/models/run.rb:464  (EXISTING, 🆕 NEW "documents" preload added)
        |
        v
  Driver::RunSerializer
    app/serializers/driver/run_serializer.rb  (EXISTING, 🆕 NEW "documents"
    field: [{id, type, status, url}])
        |
        v
[Driver App] persists payload offline, renders QR from url on-device


--- roadside scan, any time ---

[Inspector] --GET /document/:token--> [hagmonia]
  🆕 NEW AnonymousController subclass (EXISTING pattern:
  app/controllers/anonymous_controller.rb)
        |
        v
  documents.find_by(token:)
    app/models/generated_document.rb  (BUILT, this epic - Phase 0)
        |
   +--------+---------+-----------+----------+
   |        |         |           |
   v        v         v           v
 unknown  expired   artifact    valid +
 token   (expires_  not         retrievable
         at past)   retrievable
   |        |         |           |
  404      410       410         302 -> Storage::UploadStorage#generate_content_url
                                          app/services/storage/upload_storage.rb:15
                                          (EXISTING) -> signed URL -> PDF download


--- run end ---

[hagmonia] run-ended event (EXISTING) -> [RabbitMQ] -> [hagmonia-js]
  app/services/webhooks/run_ended.js  (EXISTING consumer, 🆕 NEW side effect
  added)
        |
        v
  Document.forge({id}).save({expires_at: run_end + 7.days}, {patch: true})
    service-data: src/models/document.ts  (BUILT)
```

**Decision tree - config resolution and eligibility (🆕 new helper, hagmonia-js):**

```
resolveDocumentsConfig(merchant, team)
|
+-- team.documents_configurations is null/undefined?
|     +-- YES -> return merchant.documents_configurations (default: [])
|     +-- NO  -> return team.documents_configurations
|                (an explicit [] on the team means "generate nothing" and
|                 does NOT fall back to merchant - see BRNGG-57146 nullability
|                 note; the column must stay genuinely nullable, no default)

matchTrigger(config[], eventName)
|
+-- config is [] (either level)?          -> NOT ELIGIBLE
+-- config has entries, none match trigger -> NOT ELIGIBLE
+-- an entry.trigger === eventName         -> ELIGIBLE, use entry.documents[]
```

**Decision tree - idempotent claim (🆕 new helper, hagmonia-js):**

```
claimDocument(runId, type)
|
+-- redlock.lock(`documents:${runId}:${type}`) fails/times out?
|     -> propagate error; generation attempt fails, no auto-retry
|        (RabbitMQ never retries a failed handler at any layer in this
|        stack - accepted gap, see Risk Assessment)
|
+-- lock acquired -> check DocumentRun WHERE run_id = runId
      +-- existing row found -> return existing Document UNCHANGED
      |    (never re-render, never overwrite an artifact an inspector may
      |    have already scanned)
      +-- no existing row -> insert Document, then DocumentRun, return new Document
```

The `documents_configurations` JSON shape (`[{trigger, documents: [{type, template_id}]}]`) and the `documents`/`document_runs` column list are the source of truth for every field referenced above - both are schema-enforced (Postgres migration + `activerecord_json_validator` schema validation on the config column), not inferred from any single call site, so the diagram's field names cannot drift from what's actually persisted.

### Files

| File | Change |
|---|---|
| `hagmonia/db/migrate/20260820140000_create_documents.rb` | **Built.** New table. |
| `hagmonia/db/migrate/20260820140001_create_document_runs.rb` | **Built.** New table. |
| `hagmonia/db/migrate/20260820140002_add_documents_configurations_to_merchant_and_team_configurations.rb` | **Built.** New jsonb columns. |
| `hagmonia/app/models/generated_document.rb` | **Built.** New AR model (named `GeneratedDocument` - `Document` was already taken by an unrelated STI class). |
| `hagmonia/app/models/document_run.rb` | **Built.** New AR model. |
| `hagmonia/app/validators/documents_configuration_validation.rb` | **Built.** JSON-schema validation on the config column. |
| `service-data/src/models/document.ts` | **Built.** New model, token-on-save, derived `status`. |
| `service-data/src/models/document_run.ts` | **Built.** New join model. |
| `service-data/src/index.ts` | **Built.** Barrel export. |
| `hagmonia/app/controllers/*` (new `AnonymousController` subclass, exact name TBD) | Not started. `GET /document/:token`. |
| `hagmonia/app/controllers/api/v2/*` | Not started. Authenticated `GET /runs/:id/document/:type`. |
| `hagmonia/app/serializers/driver/run_serializer.rb` | Not started. Add `documents` field. |
| `hagmonia/app/models/run.rb` (`preload_for_serialization`) | Not started. Add `documents` preload. |
| `hagmonia-js/app/services/webhooks/` (new file, S4 handler, exact name TBD) | Not started. Trigger + gate + claim + invoke. |
| `hagmonia-js/app/services/webhooks/documents_ready.js` | Not started. New webhook type. |
| `hagmonia-js/app/services/webhooks/run_ended.js` | Not started. Add `expires_at` side effect. |
| `templates-service/app/controllers/v1/print_order.ts` | Not started. Add `template_id` param/branch. |

## 4. Feature Flag Strategy

**Decision:** ❌ No traditional boolean feature flag.

Gating is via the `documents_configurations` jsonb config column on `MerchantConfiguration`/`TeamConfiguration` (merchant column: `default: [], null: false`; team column: genuinely nullable, no default - team overrides merchant only on a real `NULL`, verified against `Team#get_team_configuration_for`'s `nil`-only fallback). An empty/absent config entry for a merchant or team means "generate nothing" - functionally off by default, satisfying epic AC 12 without a separate flag.

**Rollout plan (via config, not a deploy):**
1. Default state for every merchant/team: no `documents_configurations` entries -> no generation, no behavior change.
2. Enable for an internal/reporter merchant by adding one config entry (`{"trigger": "run_started", "documents": [{"type": "run_aggregation", "template_id": N}]}`) via existing MerchantConfiguration write paths (support tooling / DB).
3. Progressive rollout is per-merchant and per-team (team overrides merchant), with no code redeploy required to expand or contract the enabled population.

**Rollback:** remove or empty the config entry - takes effect on the next `run:started` evaluation, no cache to resync (config is read live, not cached in this design).

**Why config instead of a flag:** the config *is* the eligibility gate per S4's decision ("having a matching config entry is eligibility, no separate flag") - a boolean FF alongside it would be redundant, since the config already encodes both "on/off" and "which document type/template."

## 5. Risk Assessment

| Category | Level | Notes |
|---|---|---|
| Technical Complexity | High | First-of-its-kind cross-service write pattern for this table pair (hagmonia-js writing hagmonia's Postgres via service-data, bypassing Rails validation); first use of a Redlock-style claim for idempotent document creation. |
| Integration Risk | Medium | 4 services must agree on one derived-status computation (`pending`/`ready`/`failed`) without drifting; 2 independent serializers (driver payload, webhook) both call the same method by convention, not by a shared library today. |
| Deployment Risk | Medium | `hagmonia` schema changes are dormant until the write path (hagmonia-js) and read path (hagmonia) both ship - confirm merge-day conventions for the read-path PR specifically, since it changes runtime behavior with no boolean FF (config-gated only). |
| Performance Risk | Low | Adds one `documents` preload to an already-preloaded, hot driver-payload read path (`batch_get_with_open`) - needs an explicit N+1 regression test, not expected to be a real bottleneck given a 1:1 relationship. |
| Dependency Risk | High | Hard-blocked on Gotenberg (BRNGG-57374, no due date) for real PDF conversion - mocked for this build. Also blocked on ADEO's answer for the webhook payload envelope (Option A vs B). |

**Known Gaps:**
- A failed generation is **permanent** until a human or future reconciliation job acts - RabbitMQ never retries a failed handler at any layer in this stack, confirmed in code, and idempotent-create explicitly refuses to re-render a `failed` row. No reconciliation sweep is in scope for this build.
- Missing Article 6 fields (vehicle plate, trailer plate, shipper NIF, special-authorization-ID) render blank - confirmed deferred, not blocking.
- S5 (regeneration on route change) is out of scope entirely for this build - a run's document is generated once and never amended.
- The `documents_ready` webhook payload envelope is not finalized (Option A: run-only vs Option B: run + order identifiers) - pending a direct answer from ADEO via Liel Armoza.
- Whether cancelled tasks are included in the per-run task query, and whether a zero-task run should be skipped or generate an empty document, are both flagged, not decided.
- "One document per run+type" is enforced by an application-level lock, not a database constraint (see the claim decision tree above) - a bug in the claim path fails open (a duplicate document), not closed.

## 6. T-Shirt Estimation

**Formula:** E x C x R (each 1-4). Note: this is a whole-epic rollup for the *remaining* work (Phase 0 schema/models and Phase 1 service-data models are already built and PR'd) - not a per-story estimate.

- **Effort:** 3 - spans 4 services (hagmonia read side, hagmonia-js write side + webhook, templates-service render extension), each individually small-to-medium, but coordinated across repos with independent deploy cycles.
- **Complexity:** 3 - two genuinely novel patterns for their respective codebases (Redlock-based idempotent claim in hagmonia-js; hagmonia-js writing hagmonia-owned tables for a new table pair), plus a derived-status invariant that must stay identical across two independent serializers.
- **Risk:** 3 - two real external unknowns (Gotenberg's delivery timeline, ADEO's webhook envelope answer) that aren't resolvable by more engineering effort alone.

E x C x R = 27. *Bringg's specific floor/additive-rule table for mapping this to a t-shirt size wasn't available in this session - apply your team's standard scaling.*

**Confidence:** ~70%, given two open external blockers (ADEO envelope, Gotenberg timeline) that this estimate assumes get mocked/deferred rather than resolved inline. Recommend a buffer given confidence is below 90%.

## 7. Related Repositories

| Repository | Changes | Branch | PR Link |
|---|---|---|---|
| hagmonia | Schema (`documents`/`document_runs`), `GeneratedDocument`/`DocumentRun` models, `documents_configurations` config columns + validator - **built**. Read endpoints (`/document/:token`, `GET /runs/:id/document/:type`, serializer + preload) - **not started**. | `BRNGG-57146-documents-schema-and-models` | [hagmonia#12740](https://github.com/bringg/hagmonia/pull/12740) (schema/models only; read endpoints need a follow-up PR) |
| service-data | `Document`/`DocumentRun` models - **built, reviewed, PR'd**. | `BRNGG-57886-document-service-data-models` | [service-data#1210](https://github.com/bringg/service-data/pull/1210) |
| hagmonia-js | Write path (trigger, gate, claim, invoke), `documents_ready` webhook, run-end retention hook - **not started**. Blocked on `service-data`'s version bump + publish. | Not yet created | - |
| templates-service | `template_id` param on the render endpoint - **not started**. Blocked on Gotenberg (mocked for now). | Not yet created | - |
| upload-service | No changes - existing client/API is sufficient (verified: `UploadClient#delete` with `content: true`, non-image `/content` endpoint bypass imagor). | - | - |

**Note:** hagmonia's own convention is "no FF -> merge Sunday only." The read-path PR (Phase 2, not yet opened) changes runtime behavior without a boolean FF (config-gated only, see §4) - confirm with the team whether that convention applies to config-gated changes the same way it applies to flag-less ones before scheduling that merge.

## 8. Open Questions

- **The `documents_ready` webhook payload envelope** (Option A: run-only vs Option B: run + order identifiers) - needs ADEO's direct answer, not a code decision.
- Whether cancelled tasks are included in the per-run task query for rendering - flagged, not decided.
- Whether a zero-task run should be skipped or generate an empty document - flagged, not decided.
- Where the real HTML->PDF conversion ultimately lives (a new templates-service endpoint vs. a separate Gotenberg-fronting service) - mocked either way for now, matches BRNGG-57374's own unresolved state.
- `service-data`'s version bump + Jenkins publish, and the `hagmonia-js` dependency bump, are still pending - required before hagmonia-js's write path (Phase 3) can start.
- Confirm hagmonia's Sunday-merge convention against the config-gated (not flag-gated) read-path PR, per §7's note.

## 9. Review & Approval

**Status:** 🟡 Pending Review

**Reviewer:** _TBD_
**Date:** _TBD_
**Signature:** _TBD_

**Review checklist:**
- [ ] Technical Design diagram reviewed against actual code (file:line spot-checked)
- [ ] Feature Flag / config-gating strategy approved
- [ ] Risk Assessment and Known Gaps acknowledged
- [ ] T-Shirt Estimation reviewed
- [ ] Open Questions have owners or explicit acceptance of being unresolved
