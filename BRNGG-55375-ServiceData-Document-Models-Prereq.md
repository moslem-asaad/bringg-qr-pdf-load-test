# service-data prerequisite — `Document`/`DocumentRun` models

Part of [BRNGG-55375](https://bringg.atlassian.net/browse/BRNGG-55375). Jira: [BRNGG-57886](https://bringg.atlassian.net/browse/BRNGG-57886). Full rationale in [BRNGG-55375-QR-Code-Tech-Design.md](BRNGG-55375-QR-Code-Tech-Design.md) §1. **Rewritten 2026-08-22 after a dedicated deep-research pass, including the exact `save()` override mechanics.**

**⚠️ Superseded 2026-08-22 — S4 decided against the advisory-lock approach below, in favor of Redlock** (see [BRNGG-57148-S4-Generation-Trigger-And-Write-Path.md](BRNGG-57148-S4-Generation-Trigger-And-Write-Path.md)). Practical effect: **no DB transaction is needed for the idempotent claim at all.** Redlock's lock is what serializes concurrent access — with the lock held, `DocumentRun`/`Document`'s check-then-create can be two ordinary, non-transactional `.save()`/`.fetch()` calls in sequence, exactly like `task_grouper.js`'s own `getOrCreateTaskGroupLeader` (which uses no Knex transaction either). The `pg_advisory_xact_lock` section below is kept for reference (still technically correct, and the `super.save()` override guidance above it is unaffected either way) but **is not what gets built** — don't implement it as a transaction-wrapped advisory lock; that complexity is no longer needed.

**Repo:** `service-data` (`/Users/moslemasaad/bringg/service-data`, separate from `hagmonia-js` — its own package). **Depends on:** BRNGG-57146's migration (the tables must exist in hagmonia's schema first). **Blocks:** BRNGG-57148 (S4) — hagmonia-js cannot write to `documents`/`document_runs` until this lands.

## Why this exists

No existing story covers it — it fell between S2 (schema, in hagmonia) and S4 (the writer, in hagmonia-js) because both assumed the write happened somewhere that already had model access. It doesn't; `service-data` needs new model classes first.

## Exact conventions confirmed for adding a model here

Every model must be re-exported from `src/index.ts` (a barrel) — forgetting this "silently breaks consumers," per this package's own `src/models/CLAUDE.md`. Standard shape, confirmed from `merchant_configuration.ts`/`fleet_router_rule_team.ts`:
```ts
import { instrumentPrototype } from '@bringg/service';
import Lightshelf, { PROTOTYPE_INSTRUMENTED_FUNCTIONS } from '../model';

@instrumentPrototype<Document>(PROTOTYPE_INSTRUMENTED_FUNCTIONS)
export default class Document extends Lightshelf.Model<Document> {
  public get tableName() { return 'documents'; }   // must be a getter
  public get hasTimestamps() { return true; }
}
```
`@instrumentPrototype` wraps `fetch`/`fetchAll`/`toJSON`/`save` with Prometheus timing and is applied on essentially every model — add it to both new models.

**Join-table shape — `document_runs` has its own `id` PK, so follow `FleetRouterRuleTeam`'s shape, not `ChatConversationUsers`'s.** Two existing precedents diverge on exactly this point: `chat_conversations_users.ts` is a *pure* join table with no own `id` (`idAttribute: null`), while `fleet_router_rule_team.ts` has its own `id` and uses the default `idAttribute`. Since `document_runs.id` exists per the migration, `DocumentRun` needs no `idAttribute` override:
```ts
@instrumentPrototype<DocumentRun>(PROTOTYPE_INSTRUMENTED_FUNCTIONS)
export default class DocumentRun extends Lightshelf.Model<DocumentRun> {
  public get tableName() { return 'document_runs'; }
  public get hasTimestamps() { return true; }
  public get softDelete() { return false; }   // no delete_at column
  document() { return this.belongsTo(Document); }
  run() { return this.belongsTo(Run); }
}
```
`npm run model-generator` exists but its template assumes a Redis/LRU-cached, merchant-scoped model — not a fit for either class here; hand-write both, mirroring the two files above.

## `save()` override — use `super.save()`, not prototype patching

**No existing `service-data` model overrides `save()` today** — the only cited precedent, `hagmonia-js`'s `SharedLocation.prototype.save`, uses old-style manual prototype patching (`var oldSave = SharedLocation.prototype.save; SharedLocation.prototype.save = async function() {...}`), which is the pre-TS-class idiom in that older file, not what a `service-data` TS class should copy verbatim. **The correct translation for this codebase's class style is a normal `super.save()` call** — verified against the actual library: `save` is a plain prototype method on `LightshelfModel` (`@bringg/lightshelf/src/model.js:57`, `.extend({...})`), so standard ES6 `super` semantics resolve it correctly through `class Document extends Lightshelf.Model<Document>`:
```ts
public async save(key?: any, val?: any, options?: any) {
  if (this.isNew() && !this.get('token')) {
    this.set('token', crypto.randomBytes(16).toString('base64url')); // 128 bits — not the 48-bit randomBytes(6) SharedLocation uses for its own fields, too small for this token
  }
  return super.save(key, val, options);
}
```
This is a **new pattern for `service-data`** — no existing TS example to copy verbatim, even though the underlying mechanics check out. Write a dedicated test for it before trusting it in the write path.

**Failure mode if `save()` throws:** confirmed no `try/catch` inside Lightshelf's `save()` implementation (`model.js:996-1170`) — any DB error (e.g. a hypothetical unique-violation on `token`) simply rejects the promise with the raw pg/knex error object untouched (`.code === '23505'`, `.constraint` set, nothing normalized). **No existing convention anywhere in `service-data` catches or retries a unique-violation** — searched both repos, the only related precedent is a DB-side PL/pgSQL retry loop in `hagmonia-js`'s `object_view_count.js` (a stored-function `EXCEPTION WHEN unique_violation`), not a JS-level pattern. At 128 bits of entropy, a token collision isn't worth building retry logic for — let it surface as a raw error if it ever happens, don't add speculative handling.

## The advisory-lock transaction — exact composition, and the one real gotcha

**No `pg_advisory_xact_lock` usage exists anywhere in either `service-data` or `hagmonia-js` today — this is a first-of-its-kind pattern.** But the pieces compose cleanly, confirmed:
- `lightshelf.transaction(cb)` is a pure passthrough to Knex (`@bringg/lightshelf/src/lightshelf.js:233-234`) — the callback receives a real `Knex.Transaction` object.
- That object supports `.raw(...)` directly, so `trx.raw('SELECT pg_advisory_xact_lock(?)', [lockKey])` runs on the same connection/transaction as any Lightshelf calls alongside it.
- This exact mixing (raw-transaction call + Lightshelf model calls sharing one `trx`) is already proven in production: `hagmonia-js/lib/bringg_apps/floating_inventory_app.js:463-495`.

```js
const { lightshelf, Document, DocumentRun } = require('@bringg/service-data');

await lightshelf.transaction(async trx => {
  await trx.raw('SELECT pg_advisory_xact_lock(?)', [lockKey]);

  const existing = await DocumentRun.query(qb => qb.where({ run_id: runId }))
    .fetch({ withRelated: ['document'], transacting: trx });
  if (existing) return existing.related('document');

  const document = await Document.forge({ merchant_id, type }).save(null, { transacting: trx });
  await DocumentRun.forge({ document_id: document.id, run_id: runId }).save(null, { transacting: trx });
  return document;
});
```

**⚠️ The one real gotcha, worth a code-review checklist item:** Lightshelf does **not** implicitly thread an ambient transaction through nested calls — **every single `.save()`/`.fetch()` inside the callback must explicitly receive `{ transacting: trx }`**, or that call silently runs outside the lock and outside atomicity with the rest of the block. It's easy to remember on the first call and forget on the second (e.g. `Document`'s save gets it, `DocumentRun`'s doesn't) — this would silently defeat both the transaction's atomicity and the entire point of the advisory lock. Worth a dedicated test that intentionally omits `transacting` on one call to confirm it's actually caught, not just a review reminder.

**Crash safety, confirmed:** `pg_advisory_xact_lock` is transaction-scoped — released automatically on `COMMIT` or `ROLLBACK`, including when the process crashes mid-transaction and Postgres detects the dropped connection. This is why the plan correctly chose the `_xact_` variant over session-scoped `pg_advisory_lock` — the session variant would survive across pooled-connection reuse and could silently block unrelated future transactions if an early return ever skipped an explicit unlock.

## Two options for a DB-level backstop, if the advisory lock alone ever feels insufficient

No native Postgres unique index can express "one document per `(run_id, type)`" directly, since `type` lives on `documents` and `run_id` lives on `document_runs` — cross-table unique constraints don't exist. Two options, in order of recommendation:
1. **Accept the advisory lock as the sole safety net** (recommended for a first cut) — it's correctly used by the one intended write path. Keep the given `UNIQUE (document_id, run_id)` on `document_runs` as a narrower, free backstop against double-linking the same document to the same run.
2. If a hard backstop for `(run_id, type)` specifically is wanted later (e.g. a second write path emerges that might not know to take the lock): denormalize `type` onto `document_runs` (copied at insert time, immutable after) and add a real `UNIQUE (run_id, type)` there. Costs a duplicated column; there's codebase precedent for this kind of DB-level hardening (`object_view_count.js`'s PL/pgSQL retry loop) if concurrency ever proves riskier than expected.

## Versioning and publishing — concrete, not assumed

- `package.json`: `"@bringg/service-data"`, version bumped **manually via a dedicated PR** (no `npm version` script, no auto-bump) — e.g. a real prior commit is a one-line version diff.
- **Published via Jenkins** (`Jenkinsfile`'s `Deploy` stage → `publishNpm()` from a shared CI library), not GitHub Actions — no `.github/workflows/` exists.
- `hagmonia-js` pins this package with a caret range (e.g. `^2.28.0`) — **a version-bump PR is required here first**, but once published, hagmonia-js's own `npm install`/lockfile refresh picks up any compatible new version automatically, no hagmonia-js PR needed unless pinning the exact new version explicitly.

## Testing conventions

- `test/models/`, mirroring `src/models/`. Runner is `ts-mocha` (not jest, despite jest-style matchers).
- **Real DB, no mocking** — confirmed: tests hit the same live Postgres connection Lightshelf itself uses, spun up via Jenkins with hagmonia's own migrations applied (schema comes from hagmonia exactly as expected).
- Global teardown (`test/setup/global-teardown.ts`) automatically `DELETE`s every table backing a model exported from `src/index.ts` after the suite — **`Document`/`DocumentRun`, once added to the barrel export, are covered with zero extra wiring.** (Local-only; CI tears down the whole DB container instead.)
- No factory library — raw `Model.forge({...}).save()` inline per test, with `@faker-js/faker` for random values and small helpers like `createMerchant()` from `test/database_util` for parent-row fixtures. Expect to need an equivalent `createRun()` helper if one doesn't already exist.

## Scope (updated)

1. `src/models/document.ts` — per the exact shape above, including `super.save()` override.
2. `src/models/document_run.ts` — per the exact shape above (own `id`, no `idAttribute` override).
3. Export both from `src/index.ts`.
4. Version bump via dedicated PR, publish.
5. Bump `hagmonia-js`'s `package.json` dependency, install.

## Acceptance criteria

1. `Document.forge({merchant_id, type}).save()` from a consuming service returns a row with a generated `token`, without the caller passing one.
2. Calling `.save()` again on an already-persisted `Document` does not regenerate or overwrite `token`.
3. `DocumentRun` is insertable/queryable the same way as other `service-data` join models.
4. `hagmonia-js` can `require('@bringg/service-data').Document` / `.DocumentRun` after the dependency bump, no other code changes needed to access them.
5. A transaction wrapping `pg_advisory_xact_lock` + both models' `save()` calls is atomic — a test that intentionally omits `{transacting: trx}` on one call demonstrates the failure mode (row lands outside the transaction), proving the happy path's correctness isn't accidental.
