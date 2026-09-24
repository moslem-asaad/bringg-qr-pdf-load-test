# BRNGG-55375 — Implementation Plan

Companion to [BRNGG-55375-Tech-Design-Doc.md](BRNGG-55375-Tech-Design-Doc.md) (architecture, decided) — this is the ordered, checkable build plan for the reuse-`uploads` design. Every step below is verified against the real code on each repo's `master` branch, not assumed.

**Housekeeping — abandon, don't merge:** the pre-pivot `documents`/`document_runs` schema and models exist only on two unmerged feature branches — hagmonia's `BRNGG-57146-documents-schema-and-models` and service-data's `BRNGG-57886-document-service-data-models`. Neither reached `master`. Close both PRs if opened; nothing to roll back.

---

## Phase 1 — hagmonia (no new tables) — ✅ DONE, [BRNGG-58011](https://bringg.atlassian.net/browse/BRNGG-58011), [PR #12757](https://github.com/bringg/hagmonia/pull/12757)

**Depends on:** nothing to write; Phase 3 needs `documents_configurations` deployed before it's usable.

- [x] Migration: `add_column :merchant_configurations, :documents_configurations, :jsonb, default: [], null: false` — mirrors `db/migrate/20250820095412_add_geocoding_configurations_to_merchant_configurations.rb` exactly.
- [x] Migration: `add_column :team_configurations, :documents_configurations, :jsonb` — **no default, nullable**. This asymmetry is deliberate: `??`-style team-overrides-merchant fallback in hagmonia-js only fires on `nil`, and `[].nil?` is `false` — a default of `[]` here would silently break the fallback for every team.
- [x] New `app/validators/documents_configuration_validation.rb`, mirroring `GeocodingConfigurationValidation` (`app/validators/geocoding_configuration_validation.rb`) exactly:
  ```ruby
  class DocumentsConfigurationValidation
    DATA_SCHEMA = {
      "type" => "array",
      "items" => {
        "type" => "object",
        "properties" => {
          "trigger" => { "type" => "string", "enum" => ["run_started"] },
          "documents" => {
            "type" => "array",
            "items" => {
              "type" => "object",
              "properties" => {
                "type" => { "type" => "string" }
              },
              "required" => ["type"],
              "additionalProperties" => false
            }
          }
        },
        "required" => ["trigger", "documents"],
        "additionalProperties" => false
      }
    }.freeze
  end
  ```
  Wire into both models the same way `geocoding_configurations` is wired at `app/models/merchant_configuration.rb:175`: `validates :documents_configurations, json: { schema: DocumentsConfigurationValidation::DATA_SCHEMA }, allow_blank: true` — one line in `MerchantConfiguration`, one in `TeamConfiguration`.
- [x] **Superseded during review by hagmonia#12760 ("stored upload scope helpers"):** originally planned as a hand-written `has_one` (since the existing `has_upload` concern only filtered `attachment_type`, not `stored_at`). #12760 extended `has_upload` itself to auto-generate a `stored_<name>` association (scoped to `stored_at` present) plus a `stored_<name>?` predicate, alongside the base association. `Run` model now just declares:
  ```ruby
  has_upload :run_attachment, type: 'runAggregation'
  ```
  which generates both `run_attachment` (any upload of this type) and `stored_run_attachment` (stored only) — no bespoke association needed.
- [x] `Run.preload_for_serialization` (`app/models/run.rb`) — extends the `associations:` array to include `:stored_run_attachment`.
- [x] `Driver::RunSerializer` (`app/serializers/driver/run_serializer.rb`) — add `:has_document` to the `attributes` list, plus:
  ```ruby
  def has_document
    object.stored_run_attachment.present?
  end
  ```
- [x] Tests: config validator (valid/malformed configs, both unset states skip validation); team `nil` falls back to merchant, team `[]` doesn't; `has_document` true only once `stored_run_attachment` is present (i.e. `stored_at` set, not just created); no extra query added to `batch_get_with_open` with multiple runs (N+1 guard on the new preload).
- [x] **Found in review, not in the original plan:** `documents_configurations` was missing from the strong-params allowlist on both `MerchantConfigurationUpdater#merchant_configuration_update_parameters` and `TeamConfigurationsController#team_configuration_update` — clients could never actually set it via the API despite the column/validator existing. Fixed on both, plus added to `Admin::MerchantConfigurationSerializer`, `Dispatcher::MerchantConfigurationSerializer`, and `TeamConfigurationSerializer` so it's echoed back in responses.

---

## Phase 2 — templates-service — ✅ DONE, [BRNGG-58012](https://bringg.atlassian.net/browse/BRNGG-58012), [templates-service PR #380](https://github.com/bringg/templates-service/pull/380) + [service-types PR #2141](https://github.com/bringg/service-types/pull/2141)

**⚠️ Superseded after PR #380 review (Ivan-Rudyk):** everything below documents the original two-action design (`RENDER_PRINT_ORDER` for HTML, a separate `RENDER_PRINT_ORDER_PDF` for PDF) as it was actually built — kept as-is for the history/reasoning, but it is **not** the shipped shape. Per review feedback, the two actions were merged into one (`RENDER_PRINT_ORDER` + a `format: 'html' | 'pdf'` field, `PrintOrderRenderFormat` in service-types), since it's the same operation with only the output encoding differing. `render()`/`renderPDF()` are now one `render()` method; `RenderPrintOrderPdfRpcRequest` and the separate `service_bus.ts` binding no longer exist. `render()` now always returns `download_url` (regardless of format) — the "byte-for-byte unchanged, no download_url" note below no longer holds.
- [templates-service PR #389](https://github.com/bringg/templates-service/pull/389) (stacked on #380)
- [service-types PR #2164](https://github.com/bringg/service-types/pull/2164)
- [hagmonia-js PR #7235](https://github.com/bringg/hagmonia-js/pull/7235) (Phase 3's caller, updated to match)

**Depends on:** `service-types` gets the 3 new `RenderPrintOrderRequest` fields published (blocks nothing else in this phase from being coded, just from being called for real).

**Known starting state — the on-disk WIP has more bugs than "add fields":**
- `render()` (the currently-wired HTML path, `print_order_handler.ts:75-100`) is **already broken** by the uncommitted `createNewUpload`/`overrideExistingUpload` signature change — it assigns the whole `{ uploadId, downloadUrl }` return object where `RenderPrintOrderResult.upload_id: number` is expected. Must fix as part of this phase, not treat as pre-existing/unrelated.
- `overrideExistingUpload` (lines 164-183) still uploads `Buffer.from(renderedHtml)`, `content_type: 'text/html'` — even when called from `renderPDF`'s flow (line 113 passes `renderedHtml`, not the PDF bytes). The "fileBuffer not renderedHtml" fix needs both upload helpers, not just `createNewUpload`.
- `getPdfFromHtml(renderedHtml)` (line 104) doesn't exist anywhere in the repo.
- `renderPDF` isn't bound in `service_bus.ts` — only `render` (HTML) is (line ~40).

Steps:
- [x] `service-types/types/templates.ts` — added `record_type?: string`, `record_id?: number`, `attachment_type?: string` to `RenderPrintOrderRequest`, `download_url?: string` to `RenderPrintOrderResult`, a new `TemplateRpcActions.RENDER_PRINT_ORDER_PDF` enum value, and — **found needed during review, not in the original plan** — a dedicated `RenderPrintOrderPdfRpcRequest` envelope type (mirrors `RenderPrintOrderRpcRequest` but for the new action), since Phase 3's hagmonia-js caller needs its own typed RPC envelope, not the HTML path's. Published as service-types#2141, separate from the templates-service PR since it's a different repo/publish flow.
- [x] No new `TemplateTypeEnum` value — this document reuses the merchant's existing `print_order` template (the epic aggregates the existing per-task print-receipt template, not a new one). No `template_id` field needed anywhere in this flow either.
- [x] Bumped `@bringg/types` locally (patched `node_modules` for dev, since service-types#2141 isn't published yet — real bump happens once it merges and Jenkins publishes).
- [x] Added a mocked `getPdfFromHtml(html): Buffer` in `app/helpers/html_to_pdf.ts` (plan sketched the name `htmlToPdf` — same thing, different casing/location), isolated behind one function, TODO-tagged for BRNGG-57374.
- [x] Fixed `createNewUpload`/`overrideExistingUpload` — both now take a generic `fileBuffer`/`contentType`/`fileExtension`, no HTML-buffer path in `renderPDF`'s call chain.
- [x] Fixed `render()` (HTML path) to correctly destructure `{ uploadId }` — **deviates from the original plan**: `render()` does *not* return `download_url`. Only `renderPDF()` (new code, no existing caller) does — `render()`'s only real caller (rule-service's delivery-receipt flow) never needed it, so its response shape stays byte-for-byte unchanged (confirmed no strict schema/consumer anywhere in the RPC path).
- [x] Wired `renderPDF` into `service_bus.ts` as its own `RENDER_PRINT_ORDER_PDF` action — kept as a separate public method from `render()` (not merged into one), since their return contracts genuinely differ; **deduplicated the shared logic instead** via a new private `uploadRenderedDocument` helper both methods call.
- [x] `record_type`/`record_id`/`attachment_type` passed through to `createNewUpload` when present.
- [x] Template resolution reuses `TemplateMerchant.getTemplateByType(merchant_id, TemplateTypeEnum.print_order, PRINT_ORDER_CONTENT_TYPE)` — no new enum, no `template_id`, same fallback-to-default behavior as the HTML path.
- [x] Tests: stores as `application/pdf`; template fallback behavior; existing HTML print-receipt path unchanged (byte-for-byte, verified via the untouched `render()` response shape); `download_url` on the PDF path. **Found in review:** `test/app/services/service_bus.test.ts`'s `PrintOrderHandler` mock had no `renderPDF`, so the unconditional `.bind()` in `registerActions()` threw during construction — added the mock, bumped the stale action-count assertion, added dispatch coverage for `RENDER_PRINT_ORDER_PDF`.
- [x] Manually verified end to end locally: real DB, real upload-service round trip via a scratch script (not committed) — got back a real `upload_id`/`download_url`, storage path confirmed `attachment_type: runAggregation` and `.pdf` extension carried through correctly.
- [x] **Local-only HTML-preview testing convenience moved off the real branch:** the uncommitted `renderPDF`-uploads-HTML-not-PDF tweak (previously sitting uncommitted on `BRNGG-58012-print-order-pdf-render`) is now committed on its own disposable branch `testing-print-order-html-preview`, opened as draft [templates-service#381](https://github.com/bringg/templates-service/pull/381) targeting `BRNGG-58012-print-order-pdf-render` (not master) — never to be merged. The real branch's `print_order_handler.ts` is back to its clean, real-PDF-path state. Resolves the former blocker #3.

---

## Phase 3 — hagmonia-js (`DocumentsApp`) — ✅ DONE, [BRNGG-58013](https://bringg.atlassian.net/browse/BRNGG-58013), [PR #7183](https://github.com/bringg/hagmonia-js/pull/7183)

**⚠️ Superseded, see Phase 2's note:** step below calling `RENDER_PRINT_ORDER_PDF` was updated in [hagmonia-js PR #7235](https://github.com/bringg/hagmonia-js/pull/7235) to call the merged `RENDER_PRINT_ORDER` action with `format: PrintOrderRenderFormat.pdf` instead. That PR also raised the RPC timeout (20s→90s) and the Redlock TTL (30s→100s) — the 20s/30s figures in the "Redlock claim" step below are stale.

**Branched off Phase 4's branch** (`BRNGG-58014-documents-ready-webhook`), since `DocumentsApp` fires the webhook Phase 4 built — PR targets that branch, not `master`.

- [x] New `lib/bringg_apps/documents_app.js`, structured like `back_to_warehouse_app.js` (extends `BaseBringgApp`, constructed with `ApplicationUuid.DocumentsApp` — passing `null` throws, `base_bringg_app.js:99-101` — `registerQueue(REGISTRATION_TYPES.RUN_STARTED, this.onRunStarted)` in `setup()`, gate-then-stop shape) — does **not** use `back_to_warehouse_app.js`'s config mechanism (`ApplicationMerchantConfiguration`/`getConfiguration`) — that's a different, app-scoped config system, irrelevant here since eligibility is driven entirely by `documents_configurations`. Uses the plain `MerchantConfiguration`/`TeamConfiguration` service-data models instead, matching the `??` fallback already used at `lib/bringg_apps/middle_mile_app.js:698-706`.
  - **Prerequisite found while starting this phase:** `MerchantConfiguration` (hagmonia-js's own hand-rolled model, `app/models/merchant_configuration.js`) needed `documents_configurations` added to its Redis `redisParsers` (`.jsons(['documents_configurations'], [])`) and `toRedis()` stringify list — without it, the value came back from Redis as an unparsed JSON string, not a real array. **`TeamConfiguration` needed no equivalent fix** — it's imported straight from `@bringg/service-data`, whose generic `Finder`/`SchemaBasedRedisSerializer` auto-detects jsonb columns from the real Postgres schema.
- [x] Resolves the run's task_ids by mirroring `loading_ended.js`'s `fetchTasksByRunId({merchantId, runId})`, plus an explicit `whereNot({status: Task.STATUS.cancelled})` — **decided answer to the "cancelled tasks?" open question**: once a run has started, the document shows only active tasks, cancelled tasks excluded (other statuses, e.g. done, stay in). A run whose only tasks are cancelled is treated the same as a zero-task run (skipped, no render, no webhook).
- [x] Redlock claim on `(run_id, type)`, mirroring `TaskGroupLeaderService`'s pattern but with its own, longer TTL (30s lock, 20s RPC timeout) sized for a full render+store round trip, not `task_grouper.js`'s 2s quick-claim constant. `Upload.findStored` inside the lock provides idempotency.
- [x] Calls templates-service directly via the base `RpcClient` (deep-imported the same way `back_to_warehouse_app.js` already deep-imports `TasksCreator`) with `TemplateRpcActions.RENDER_PRINT_ORDER_PDF` — **confirmed no generic `render` method exists on `TemplatesRpcClient`**, and adding one there was ruled out of scope for this PR (a separate shared-package change).
- [x] On success, fires the webhook directly via `webhookApp.onWebhookEvent('DocumentsReady', EventType.DocumentsReady, {merchant_id, run_id, documents: [{id, type, url}]}, logMeta)` — confirmed exact call, matching Phase 4's own production-path tests. `EventType.DocumentsReady` isn't tied to any internal RabbitMQ queue, so nothing else would trigger it.
- [x] On failure (RPC throws or returns `success: false`): logs and returns, no partial state — safe for a future `run:started` republish to retry cleanly.
- [x] Tests: no config match → no-op; team override/fallback (both `[]` and no-row-at-all); zero-task run → skipped; run whose only tasks are cancelled → skipped, same as zero-task; matching config → correct request shape (cancelled sibling task excluded from `task_ids`) + webhook fired with the render result; already-stored → idempotent skip; two concurrent `run:started` events → exactly one render call; RPC throws or returns failure → no webhook, no partial state.
- [x] **Cross-repo additions found while building this phase, folded into `service-types#2141` (same branch as Phase 2):** `'Run'`/`'runAggregation'` added to `RecordType`/`AttachmentType` (used by `Upload.findStored` and the upload-service record-lookup path without being declared in the type), and a new `ApplicationUuid.DocumentsApp` (every Bringg App needs a registered identity to initialize, even though this one's eligibility gating doesn't use per-merchant Application activation at all).
- [x] **Manually verified end-to-end locally** against real templates-service + upload-service instances (both built/started from their branches, pointed at the same dev Postgres/Redis/RabbitMQ) — full RPC round trip, real `uploads` row created, real `download_url` returned. Confirmed the failure path independently first (both dependent services down → clean timeout, no partial state) before bringing them up for the happy path.
- [x] **CI blocker found and worked around:** `@bringg/types` pinned to the unmerged `service-types#2141` pre-release (`v4.273.0-pre.0`) fails `npm ci` in Jenkins — `@bringg/optimization-request-utils`'s peer range (`^4.186.5`) doesn't semver-match a pre-release tag even though the version is numerically newer. Temporarily patched this branch's `Jenkinsfile` with `--legacy-peer-deps` to unblock a test build. **Second occurrence found later:** the Docker build stage (`docker build ...`) runs its own separate `npm ci --omit=dev` inside `Dockerfile` (not the Jenkinsfile's `sh` step) — same ERESOLVE failure, caught when PR #7183 showed `UNSTABLE` CI. Patched with the same `--legacy-peer-deps` flag, verified locally (`npm ci --omit=dev --legacy-peer-deps` against a copy of `package.json`/`package-lock.json` resolves cleanly, 1018 packages, no ERESOLVE). **Must revert all three** (the Jenkinsfile flag, the Dockerfile flag, and the `@bringg/types` pin) once `service-types#2141` merges and publishes a real stable version.

---

## Phase 4 — `documents_ready` webhook — ✅ DONE, [BRNGG-58014](https://bringg.atlassian.net/browse/BRNGG-58014), [PR #7180](https://github.com/bringg/hagmonia-js/pull/7180)

**Can be built independently of Phase 3, wired in at the end.**

- [x] New `app/services/webhooks/documents_ready.js`. **Deviates from the original plan in a few ways, found during implementation:**
  - `multiModels: true`, `onlyFlexible: true`, `baseModel: 'run_and_documents'` (not `'run'`) — needed so the payload can carry two independent top-level keys (`run`, `documents`) rather than nesting one under the other.
  - `eventType` is `EventType.DocumentsReady` from `@bringg/types` (added there as `'documents_ready'`, matching the existing `webhookType` naming — required a `service-types` publish + `@bringg/types` bump in hagmonia-js), not a local string constant as originally sketched.
  - `flexibleSerialize()` is overridden directly, **not** left to the inherited `multiModels` default. Found in review: the generic default-structure mechanism (`defaultRelations`/`defaultFields` on `flexibleModelConfig()`) is admin-UI metadata only, never consulted at runtime — without the override, an unconfigured merchant got `{}` back instead of the real payload.
  - **`documents` is never admin-configurable — always fixed fields (`id`, `type`, `url`), never read from `config.structure`.** Confirmed against the real admin webhook-config UI screenshot: `documents` has no backing DataService, so that UI can only ever show `run` as a pickable branch, never `documents`. Only `run`'s fields/relations come from admin config (falling back to a full default including `tasks` when unconfigured).
- [x] Reuse the existing light `case 'run':` attribute path (`base_webhook.js:349-357`, backed by `RunDataService`) for `run.id`/`run.external_id`/`run.tasks[].{id, external_id}` — do not write new fetch code for this part, just configure `fields`/`relations`.
- [x] New `case 'documents':` branch in `fetchWebhookData` — passes `message.documents` straight through (never re-fetched by id, avoids a read-after-write race). Phase 3 must publish the event message with `documents: [{id, type, url}]` already shaped this way.
- [x] Register in `app/services/webhooks/index.js`.
- [x] Absent-not-empty: `documents` key absent (not `[]`) when the merchant has no document for this run.
- [x] Tests: payload shape matches §7.6 exactly (nested `run`/`tasks`/`documents`); `documents` fields stay fixed even if a config tries to restrict them; **delivery boundary and no-op-without-subscription tested through the real production entrypoint** (`webhookApp.onWebhookEvent`, not `flexibleSerialize` called directly) — found in review that calling `flexibleSerialize` directly doesn't exercise the actual delivery/subscription-gating path at all.

---

## Phase 5 — Integration smoke test (manual)

- [ ] Set `documents_configurations` on a test merchant: `[{"trigger": "run_started", "documents": [{"type": "runAggregation"}]}]`, and configure that merchant's `print_order` template via the normal template CRUD flow (no new template type — this document reuses the existing print-order template).
- [ ] Start a multi-stop route → confirm an `uploads` row appears with `record_type: 'Run', record_id: <run_id>, attachment_type: 'runAggregation', stored_at` set, and `documents_ready` fires to a test webhook endpoint with the right shape.
- [ ] Call `batch_get_with_open` for the run → confirm `has_document: true`.
- [ ] Ask upload-service for the file link as the Driver App would (its own login) → confirm a working signed URL, valid ~7 days.
- [ ] Start a route on a merchant/team with no matching config → confirm no upload row, no webhook, `has_document: false`.
- [ ] Trigger `run:started` twice for the same run (or replay the event) → confirm only one `uploads` row.

---

## Suggested PR order

1. ✅ Phase 1 (hagmonia) — config columns + validator + `run_attachment`/`has_document` — no cross-repo dependency, start immediately. **Done**, PR open.
2. ✅ Phase 2 (templates-service) — also independent. **Done**, both PRs open (templates-service#380, service-types#2141); needs service-types published before hagmonia-js can depend on a real (non-pre-release) version.
3. ✅ Phase 3 (hagmonia-js) — needs Phase 1 deployed and Phase 2 available (or stubbed). **Done**, PR open (hagmonia-js#7183, targets Phase 4's branch). Currently running against the `service-types#2141` pre-release via a temporary `--legacy-peer-deps` CI workaround — both need reverting once that PR merges and publishes for real.
4. ✅ Phase 4 (webhook) — code anytime, wire the live call into Phase 3 last. **Done**, PR open (hagmonia-js#7180). Phase 3 now publishes `EventType.DocumentsReady` with the `{merchant_id, run_id, documents: [{id, type, url}]}` shape this expects.
5. Phase 5 — after everything above is deployed together. Not yet started for real, but the core flow (trigger → render → store → webhook) has been manually verified end-to-end locally against real templates-service + upload-service instances.
