# BRNGG-57146 (S2) — `documents`/`document_runs` schema + hagmonia read path

Part of [BRNGG-55375](https://bringg.atlassian.net/browse/BRNGG-55375). Full rationale in [BRNGG-55375-QR-Code-Tech-Design.md](BRNGG-55375-QR-Code-Tech-Design.md) §1/§5; ordering in [BRNGG-55375-QR-Code-Implementation-Plan.md](BRNGG-55375-QR-Code-Implementation-Plan.md) Phase 0/2.

**Repo:** `hagmonia`. **Depends on:** nothing — start immediately. **Blocks:** the service-data prerequisite ticket, S4's write path, S6's serializer work.

## ✅ Phase 0 implemented 2026-08-20 (schema only — Phase 2 read endpoints not started)

The three migrations, `GeneratedDocument`/`DocumentRun` models, the `Run` association, and JSON-schema validation on both config columns (`app/validators/documents_configuration_validation.rb`, wired into `merchant_configuration.rb`/`team_configuration.rb` via `activerecord_json_validator` — mirrors the existing `GeocodingConfigurationValidation` pattern; verified it rejects malformed entries and accepts both "unset" states) are done and merged locally. ER diagram + worked example in the tech design doc §1. Files: `db/migrate/20260820140000_create_documents.rb`, `20260820140001_create_document_runs.rb`, `20260820140002_add_documents_configurations_to_merchant_and_team_configurations.rb`, `app/models/generated_document.rb`, `app/models/document_run.rb`, `app/models/run.rb` (association added). **`db/schema-locked.rb` did not regenerate from the normal `db:migrate` run** — no script for it was found in the repo; needs whatever process normally refreshes that file before this is committed.

## 🔴 Independent review 2026-08-23 found a real, verified bug — now fixed

Sent a fresh subagent (no memory of writing this code) to review the diff cold. It found one critical bug and confirmed everything else:

1. **`GeneratedDocument#document_runs`/`#runs` raised `PG::UndefinedColumn`, always.** `has_many` derives its foreign key from the **model class name**, not `self.table_name` — `"GeneratedDocument".foreign_key` → `generated_document_id`, which doesn't exist; the real column is `document_id`. `Run`'s side of the same association happened to work by coincidence (its class name matches its table), which is exactly why this survived the earlier `rails runner` smoke test — that test only exercised `run.generated_documents`, never `document.runs`. **Verified the bug first** (reproduced the exact `PG::UndefinedColumn` via `rails runner`), then fixed:
   ```ruby
   has_many :document_runs, foreign_key: :document_id, inverse_of: :document, dependent: :destroy
   ```
   Re-verified fixed. Also added `belongs_to :upload, optional: true` (there was no way to reach the artifact from the model at all) and `inverse_of: :document_runs` on `DocumentRun`'s side.
2. **`allow_blank: true` on both `validates :documents_configurations` lines let a bare `{}` (Hash) and unparseable JSON strings silently pass validation and save as `{}`** — `Hash#blank?` is `true`, so the schema check never ran. Fixed to `allow_nil: true`, which still accepts `nil` (team fallback) and `[]` (both models) but now correctly rejects `{}`. Verified before/after.
3. Minor, also fixed: `minItems: 1` on the inner `documents[]` schema (an entry with an empty array was a meaningless no-op that validated fine), `dependent: :destroy` on `Run`'s side of the association too, an `expires_at` index (an expiry sweep would have seq-scanned `documents`), a `STATUSES` constant.
4. **Declined one suggestion on purpose:** adding `enum` constraints to `trigger`/`documents[].type` in the JSON schema. Confirmed via the Phase 3 (S4) research that the schema's openness there is deliberate — evidence future trigger/type values are anticipated — so constraining it now would reverse a decision already made for a real reason, not fix an oversight.
5. **Added specs** (none existed before this pass, a real gap per this repo's own `CLAUDE.md`): `spec/models/generated_document_spec.rb`, `spec/models/document_run_spec.rb`, `spec/validators/documents_configuration_validation_spec.rb`, `spec/factories/generated_documents.rb`. All 20 examples pass against a freshly-migrated test DB (`RAILS_ENV=test bundle exec rails db:migrate` was needed first — the test DB doesn't share migration state with dev).

## ⚠️ Read first — 2026-08-20 scope correction

This ticket's original write-path ACs (create, idempotency, regeneration invariants) assumed Ruby/ActiveRecord ownership. **That's no longer true.** hagmonia owns the **schema and the read path only** — the actual create/idempotent-write logic is implemented in `hagmonia-js` (see the S4 doc). Don't build create/idempotency logic here; if you're implementing this ticket, your job stops at "the tables exist and can be read correctly."

## What this ticket builds

1. **Migration** — `documents`:
   ```
   id             bigint   PK
   merchant_id    bigint   NOT NULL
   type           string   NOT NULL   -- "run_aggregation"; enumerated in code, not a DB enum
   token          string   NOT NULL   -- UNIQUE
   upload_id      bigint   NULL
   failed_at      datetime NULL
   failure_reason string   NULL
   expires_at     datetime NULL
   created_at, updated_at
   ```
   Unique index on `token`, index on `merchant_id`.

2. **Migration** — `document_runs`:
   ```
   id            bigint PK
   document_id   bigint NOT NULL
   run_id        bigint NOT NULL
   UNIQUE (document_id, run_id)
   INDEX (run_id)
   ```

3. **Migration** — add `documents_configurations` as a dedicated `jsonb` column, **with different nullability on each table — this is not symmetric, and getting it wrong silently breaks the team-overrides-merchant fallback:**
   - `merchant_configurations`: `default: [], null: false` (mirrors the `geocoding_configurations` precedent — merchant is the top of the hierarchy, nothing to fall back to).
   - `team_configurations`: **plain nullable column, no default.** `Team#get_team_configuration_for(name)` (`app/models/team.rb:203-208`) only falls back to the merchant when the value is `nil` — an empty array is not `nil`. **Verified by actually running it:** with `default: [], null: false` on both (the first version of this migration), every team permanently reads as "explicitly configured to generate nothing," regardless of the merchant's config — the fallback never triggers. Fixed by making the team column nullable with no default; re-tested and confirmed correct. **Do not copy the `geocoding_configurations` pattern onto the team table.**
   - Do not nest either under `side_menu_features`.

4. **Read-only models — `app/models/generated_document.rb`, `app/models/document_run.rb`.** ⚠️ Not `Document` — that class already exists (`app/models/document.rb`, an STI subtype of `TaskNote`, unrelated) and this original plan missed that collision. The new model is `GeneratedDocument`, `self.table_name = "documents"`, and **must also set `self.inheritance_column = nil`** — `type` is a plain enumerated string column here (`"run_aggregation"`), not an STI discriminator, and Rails will try to use it as one (and break) without that override. hagmonia never writes these (see correction above), but needs AR classes to query through. Add the derived `status` method here:
   ```ruby
   def status
     return "failed" if failed_at.present? && upload_id.nil?
     upload_id.nil? ? "pending" : "ready"
   end
   ```
   `pending`/`ready`/`failed` — never a stored column. This exact method is what both the driver serializer (S6) and the webhook (S2.1) must call, not recompute independently.

5. **`Run` model** — `has_many :document_runs`, `has_many :documents, through: :document_runs`.

6. **`GET /document/:token`** — new `AnonymousController` subclass. **Rewritten 2026-08-22 after a deep-research pass — several assumptions below were wrong or under-specified; this is now implementation-ready.**

   **The `AnonymousController` pattern, confirmed exactly** (`app/controllers/anonymous_controller.rb:1-8`):
   ```ruby
   class AnonymousController < ApplicationController
     skip_before_action :authenticate_user_from_token!
     skip_before_action :authenticate_user!
   end
   ```
   It skips only those two before_actions — everything else `ApplicationController` wires up (structured request logging via `append_info_to_payload`, origin tracking) still runs, with `current_user` simply `nil`. Mirror `app/controllers/oidc_controller.rb` for the "root-level anonymous controller" shape (not namespaced under an authenticated API namespace).

   **⚠️ `Storage::UploadStorage#generate_content_url` does NOT check artifact existence — this needs new code, not reuse.** Full method (`app/services/storage/upload_storage.rb:15-19`):
   ```ruby
   def generate_content_url(upload, exp = 1.day)
     return unless upload
     self.presigned_get_url(self.file_path(upload), exp)
   end
   ```
   It only returns `nil` if `upload` itself is `nil` — the actual signing (`presigned_get_url` → `cloud_storage.rb:41-44`) is a **pure local HMAC computation**, never a network call to storage. So if the `Upload` row exists but the object is gone (or was never fully stored), this method happily returns a syntactically valid signed URL that 404s only when the inspector's browser actually fetches it — i.e. exactly the `302`-to-a-dead-object failure mode this whole design is supposed to prevent. **Also confirmed: `uploads.stored_at`/`uploads.ttl` — the columns that look purpose-built for exactly this check — are completely unused anywhere in hagmonia's Ruby code** (zero references outside `db/schema.rb`); there is no existing "is this upload retrievable" predicate anywhere in this repo to reuse. Build one using `Storage::CloudStorage#file_content_length` (`cloud_storage.rb:50-68`), which *does* do a real existence check (a HEAD-style lookup against the bucket) but isn't currently wired into anything — call it before signing, treat `nil` as "not retrievable" → `410`.

   **`GeneratedDocument` has no `belongs_to :upload`** — it only stores a bare `upload_id` FK. Resolve the artifact manually: `Upload.find_by(id: document.upload_id)`.

   Full logic:
   - `GeneratedDocument.find_by(token:)` → `404` if not found.
   - Past `expires_at` → `410`.
   - `upload_id` nil (derived `pending`/`failed`) → `404`. **Keep this as `404`, not `202`, even for `pending`** — this is a bare browser navigation from an inspector's phone with no XHR reading the status code; `202` renders as a blank/generic page and gains nothing, while `404` lets you render an actually useful human message ("this document is still being generated"). Distinguish pending-vs-truly-missing in the structured log's outcome field instead, not via HTTP status.
   - `Upload.find_by(id: document.upload_id)` nil, or `file_content_length` on it returns nil (not retrievable) → `410`.
   - Otherwise: `generate_content_url` → `302`, `Content-Disposition: attachment`.
   - **`404`/`410` bodies must be human-readable.** No existing precedent for this in hagmonia (every controller uses the `{success, message, rc}` JSON contract), but `render plain:`/`render html:` work fine under this `ActionController::API` app (proven by `diagnostics_controller.rb`/`open_fleets_controller.rb`, which already do this for other endpoints) — e.g. `render plain: "This document link is no longer valid.", status: :gone`.
   - **Logging: do NOT log the raw token.** This app's own `config/initializers/090_filter_parameter_logging.rb` explicitly adds `:token` to `Rails.application.config.filter_parameters` — but that filter only touches `request.filtered_parameters` (the automatic per-request log), **not** a custom `Rails.logger.info(token: ..., ...)` call, which bypasses it entirely. Logging the full token in a custom line here would directly violate both this repo's own filter convention and its `CLAUDE.md` rule ("exclude tokens" from logs). Log a truncated form instead (`token_prefix: token.first(6), token_suffix: token.last(4)`) and, once resolved, `document_id` as the primary searchable top-level field — that's an internal, non-sensitive, already-"safe" ID per the logging convention, and is more useful for support tracing than the token itself.
   - **Rate limiting is NOT verified to exist anywhere for this class of endpoint.** No rack-attack or similar middleware exists in hagmonia at all (confirmed absent from `Gemfile`). The design assumes edge/gateway rate limiting handles this — that assumption is unverified from inside hagmonia; if it matters, confirm with whoever owns `api-gateway`/edge config rather than treating it as settled.

7. **`GET /runs/:id/document/:type`** — authenticated, merchant-scoped. **Confirmed exact idiom to follow**, from this exact controller (`app/controllers/api/v2/runs_controller.rb:72`):
   ```ruby
   run = Run.find_by!(id: run_id, merchant_id: current_user.merchant_id)
   ```
   Scope the lookup with `merchant_id: current_user.merchant_id` directly in the query — a mismatched merchant just doesn't match, `ActiveRecord::RecordNotFound` → `404`. Then reach the document via the already-preloadable `run.generated_documents` association (see the S6 preload note below), not an independent `GeneratedDocument` lookup with a manual merchant cross-check — no Pundit policy exists for `Run`/`GeneratedDocument` in this codebase; merchant-scoped `find_by!` is the actual established convention here, not `authorize`.

## S6 — driver payload serializer, exact mechanics

`Run.preload_for_serialization` (`app/models/run.rb:466-470`) — the one-line diff, confirmed exact:
```ruby
ActiveRecord::Associations::Preloader.new(records: records, associations: [:planned_route, :generated_documents]).call
```
(a single `Preloader#call` accepts an array of association names — same idiom the method's own `preload_end_location` helper already uses per-group with a single symbol.)

`Driver::RunSerializer` conditional-field idiom, confirmed from the existing `end_location` field (`app/serializers/driver/run_serializer.rb`) and `panko_customer_serializer.rb`'s `phone`: declare the attribute name, define a same-named method, return `nil` when not applicable — Panko's `method_added` hook automatically wires this up. **But this Panko version (0.8.5, confirmed via `Gemfile.lock`) has no `if:`/`unless:` DSL** — for a key that must be **entirely absent** (not just `null`) when there's no document, or for `url` specifically absent unless `status == "ready"`, use `Panko::Serializer::SKIP` (`panko_serializer-0.8.5/lib/panko/serializer.rb:35`): a method-backed attribute returning this sentinel is omitted from the output JSON entirely. **This has zero existing usage anywhere in hagmonia today** — it's the correct native mechanism, not a workaround, but it's a first-of-its-kind pattern in this codebase, worth a code-review callout rather than assuming reviewers have seen it before.

## Tests

- `404`/`410`/`302` cases for the token endpoint, including the "past `expires_at`" and "artifact gone" branches **as separate test cases** — they're now separate checks (`expires_at` vs. `file_content_length`), not one combined condition.
- `status` derivation covering all lifecycle states (pending / ready / failed / failed-but-previous-artifact-still-serving).
- Token uniqueness/lookup correctness (altering one character of a valid token → `404`).
- The token endpoint's structured log never contains the full token value (assert on log output directly, not just behavior).
- `Panko::Serializer::SKIP` actually omits the key (not just nulls it) — assert on the serialized JSON's key set, not just the value.
- `Run.preload_for_serialization` with `documents` — an explicit query-count assertion (N+1 regression guard), since this is the hottest read path in the driver API.

## Acceptance criteria

1. Migrations apply cleanly; `documents`/`document_runs` exist with the exact schema above.
2. `documents_configurations` exists as a real column on both config tables, mergeable via `get_team_configuration_for`.
3. `GET /document/:token` returns the correct status code in all four branches above, and never a `302` to a dead/expired artifact.
4. `GET /runs/:id/document/:type` is merchant-scoped — a user from merchant A cannot read merchant B's document.
5. `status` is computed in exactly one place, used by every consumer of this model.
